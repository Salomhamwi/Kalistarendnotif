import threading
import time
import sys
from colorama import init, Fore, Style
import cv2
import numpy as np
import pyautogui
import pytesseract
import keyboard
import tkinter as tk
from tkinter import font as tkfont, ttk
import math
import queue
from concurrent.futures import ThreadPoolExecutor

# Initialize colorama
init()

# Tesseract path
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Screen regions to monitor
REGIONS = {
    'AD': (544, 983, 574, 1008),
    'AP': (613, 981, 642, 1005),
    'ARMOR': (22, 27, 43, 47),
    'LEVEL': (707, 1049, 728, 1069),
    'STACKS': (233, 101, 256, 116),
    'HP': (163, 23, 194, 44),
    'EPIC_TOGGLE': (1272, 1048, 1341, 1076)
}

# Game state tracking
current_state = {
    'level': 1,
    'ad': 0,
    'ap': 0,
    'armor': None,
    'hp': None,
    'stacks': None,
    'target_visible': False,
    'epic_mode': False,
    'rend_rank': 1
}

# Thread synchronization
state_lock = threading.Lock()
overlay_queue = queue.Queue()
shutdown_event = threading.Event()

# OCR Processing
ocr_executor = ThreadPoolExecutor(max_workers=4)

class OCRProcessor:
    @staticmethod
    def preprocess_image(img, region_type):
        """Optimized preprocessing for different regions"""
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            if region_type in ['hp', 'stacks']:
                _, thresh = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
                thresh = cv2.resize(thresh, None, fx=1.2, fy=1.2)
                kernel = np.ones((1,1), np.uint8)
                return cv2.erode(thresh, kernel, iterations=1)
            else:
                return cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)[1]
        except Exception as e:
            print(f"Preprocessing error: {e}")
            return None

    @staticmethod
    def read_number(img, region_type):
        """Thread-safe OCR reading"""
        try:
            if img is None:
                return None
                
            config = "--oem 1 --psm 7" if region_type in ['hp', 'stacks'] else "--oem 3 --psm 10"
            text = pytesseract.image_to_string(
                img, 
                config=f"{config} -c tessedit_char_whitelist=0123456789"
            ).strip()
            return text if text.isdigit() else None
        except Exception as e:
            print(f"OCR error: {e}")
            return None

def capture_region(region):
    """Thread-safe region capture"""
    try:
        x1, y1, x2, y2 = region
        screenshot = pyautogui.screenshot(region=(x1, y1, x2-x1, y2-y1))
        return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    except Exception as e:
        print(f"Capture error: {e}")
        return None

def process_region(region, region_type):
    """Process a single region in thread pool"""
    img = capture_region(region)
    if img is None:
        return None
        
    processed = OCRProcessor.preprocess_image(img, region_type)
    if processed is None:
        return None
        
    return OCRProcessor.read_number(processed, region_type)

def get_rend_rank(level):
    """Determine Rend rank based on character level"""
    if level >= 9: return 5
    if level >= 7: return 4
    if level >= 5: return 3
    if level >= 4: return 2
    return 1

def monitor_stats():
    """Combined monitoring thread with optimized OCR"""
    last_values = {key: None for key in ['hp', 'stacks', 'ad', 'ap', 'armor', 'level']}
    iteration = 0
    
    while not shutdown_event.is_set():
        try:
            # Process dynamic regions (HP and stacks) every iteration
            futures = {
                'hp': ocr_executor.submit(process_region, REGIONS['HP'], 'hp'),
                'stacks': ocr_executor.submit(process_region, REGIONS['STACKS'], 'stacks')
            }
            
            # Process static regions every 10 iterations
            if iteration % 10 == 0:
                futures.update({
                    'ad': ocr_executor.submit(process_region, REGIONS['AD'], 'ad'),
                    'ap': ocr_executor.submit(process_region, REGIONS['AP'], 'ap'),
                    'armor': ocr_executor.submit(process_region, REGIONS['ARMOR'], 'armor'),
                    'level': ocr_executor.submit(process_region, REGIONS['LEVEL'], 'level')
                })
            
            # Process results
            for region_type, future in futures.items():
                text = future.result()
                if text is not None:
                    try:
                        current_value = int(text)
                        
                        # Apply validation rules
                        if region_type == 'stacks' and 90 <= current_value <= 99 and last_values['stacks'] and 18 <= last_values['stacks'] <= 29:
                            current_value = last_values['stacks'] + 1
                        elif region_type == 'level' and last_values['level'] == 10 and current_value == 1:
                            current_value = 11
                            
                        if last_values[region_type] != current_value:
                            with state_lock:
                                current_state[region_type] = current_value
                                if region_type == 'level':
                                    current_state['rend_rank'] = get_rend_rank(current_value)
                            last_values[region_type] = current_value
                            color = Fore.GREEN
                            if region_type == 'hp': color = Fore.BLUE
                            elif region_type == 'stacks': color = Fore.MAGENTA
                            print(f"{color}{region_type.upper()}: {current_value}{Style.RESET_ALL}")
                    except ValueError:
                        pass
            
            # Update target visibility
            with state_lock:
                current_state['target_visible'] = current_state['hp'] is not None
            
            iteration += 1
            time.sleep(0.05)  # ~20fps
            
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(1)

def monitor_epic_toggle():
    """Monitor epic toggle state"""
    last_state = False
    
    while not shutdown_event.is_set():
        try:
            img = capture_region(REGIONS['EPIC_TOGGLE'])
            if img is not None:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
                current_state_val = np.mean(thresh) > 100
                
                if current_state_val != last_state:
                    with state_lock:
                        current_state['epic_mode'] = current_state_val
                    overlay_queue.put("EPIC_ON" if current_state_val else "EPIC_OFF")
                    print(f"{Fore.MAGENTA}Epic Mode: {'ON' if current_state_val else 'OFF'}{Style.RESET_ALL}")
                    last_state = current_state_val
        except Exception as e:
            print(f"Epic toggle error: {e}")
        
        time.sleep(0.2)

def calculate_rend_damage(character_level, attack_damage, ability_power, stacks, target_armor, epic_mode, rend_rank):
    """Calculate Kalista's Rend damage with AP scaling and epic mode"""
    rank_index = rend_rank - 1
    
    # Base damage values with AP scaling
    base_damage = [10, 20, 30, 40, 50][rank_index] + (0.2 * ability_power)
    per_stack_damage = [7, 14, 21, 28, 35][rank_index] + (0.2 * ability_power)
    
    # AD ratios
    initial_ad_ratio = 0.7
    per_stack_ad_ratio = [0.2, 0.25, 0.3, 0.35, 0.4][rank_index]
    
    if stacks < 1:
        return 0
    
    # Initial spear damage
    total_damage = base_damage + (attack_damage * initial_ad_ratio)
    
    # Additional spears damage (stacks - 1)
    if stacks > 1:
        additional_stacks = stacks - 1
        total_damage += additional_stacks * (per_stack_damage + (attack_damage * per_stack_ad_ratio))
    
    # Apply epic mode reduction
    if epic_mode:
        total_damage *= 0.5
    
    # Apply armor reduction
    if character_level >= 13:
        effective_armor = target_armor * 0.7
    else:
        effective_armor = target_armor
    
    # Calculate damage multiplier from armor
    if effective_armor >= 0:
        damage_multiplier = 100 / (100 + effective_armor)
    else:
        damage_multiplier = 2 - (100 / (100 - effective_armor))
    
    return total_damage * damage_multiplier

def execute_indicator():
    """Handle execute detection and overlay updates"""
    while not shutdown_event.is_set():
        with state_lock:
            level = current_state['level']
            ad = current_state['ad']
            ap = current_state['ap']
            stacks = current_state['stacks']
            hp = current_state['hp']
            armor = current_state['armor']
            target_visible = current_state['target_visible']
            epic_mode = current_state['epic_mode']
            rend_rank = current_state['rend_rank']
        
        if not target_visible or None in (hp, armor, stacks):
            overlay_queue.put("HIDE")
            time.sleep(0.01)
            continue
        
        damage = calculate_rend_damage(level, ad, ap, stacks, armor, epic_mode, rend_rank)
        remaining_hp = max(0, hp - damage)
        damage_percent = min(1.0, damage / hp) if hp > 0 else 0
        
        if damage >= hp:
            overlay_queue.put("SHOW")
            sys.stdout.write('\a')  # Beep
            sys.stdout.flush()
        else:
            if damage_percent > 0.7:
                overlay_queue.put(("PROGRESS", damage_percent, math.ceil(remaining_hp)))
            else:
                overlay_queue.put("HIDE")
        
        time.sleep(0.01)

class ExecuteOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        
        # Window setup
        self.root.geometry("335x54+889+871")
        self.root.lift()
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", "black")
        self.root.config(bg="#111111")
        
        # State tracking
        self.active = False
        self.last_update_time = 0
        
        # Initialize UI
        self.setup_ui()
        
        # Initially hidden
        self.root.withdraw()

    def setup_ui(self):
        """Initialize all UI components"""
        # Main frame
        self.main_frame = tk.Frame(self.root, bg="#111111", padx=0, pady=0)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Progress bar
        self.setup_progress_bar()
        
        # Bottom controls
        self.setup_bottom_controls()
        
        # Control panel
        self.create_control_panel()

    def setup_progress_bar(self):
        """Configure progress bar styles and widget"""
        self.progress_style = ttk.Style()
        self.progress_style.theme_use('clam')
        
        # Style configurations
        self.progress_style.configure("default.Horizontal.TProgressbar",
                                    thickness=20,
                                    troughcolor="#222222",
                                    background="#333333",
                                    bordercolor="#111111")
        self.progress_style.configure("ready.Horizontal.TProgressbar",
                                    background="#4CAF50")
        self.progress_style.configure("warning.Horizontal.TProgressbar",
                                    background="#FFA500")
        self.progress_style.configure("execute.Horizontal.TProgressbar",
                                    background="#FF0000")
        
        # Progress bar instance
        self.progress = ttk.Progressbar(self.main_frame, 
                                      orient="horizontal",
                                      length=335,
                                      mode="determinate",
                                      style="default.Horizontal.TProgressbar")
        self.progress.pack(fill=tk.BOTH, expand=True)

    def setup_bottom_controls(self):
        """Configure bottom status bar"""
        self.bottom_frame = tk.Frame(self.main_frame, bg="#111111")
        self.bottom_frame.pack(fill=tk.X)
        
        # Status label
        self.label = tk.Label(self.bottom_frame,
                            text="",
                            font=tkfont.Font(family="Arial", size=10, weight="bold"),
                            fg="#FFFFFF",
                            bg="#111111")
        self.label.pack(side=tk.LEFT)
        
        # Epic mode indicator
        self.epic_label = tk.Label(self.bottom_frame,
                                  text="Epic: OFF",
                                  font=tkfont.Font(family="Arial", size=10),
                                  fg="#AAAAAA",
                                  bg="#111111")
        self.epic_label.pack(side=tk.RIGHT)
        
        # Close button
        self.toggle_btn = tk.Button(self.bottom_frame,
                                  text="⏻",
                                  font=tkfont.Font(size=10),
                                  command=self.shutdown,
                                  bd=0,
                                  fg="#AAAAAA",
                                  bg="#111111",
                                  activeforeground="#FFFFFF",
                                  activebackground="#333333")
        self.toggle_btn.pack(side=tk.RIGHT, padx=5)

    def create_control_panel(self):
        """Create control panel window"""
        self.control_panel = tk.Toplevel()
        self.control_panel.title("Execute Assistant Control")
        self.control_panel.geometry("200x100+100+100")
        self.control_panel.resizable(False, False)
        
        # Control buttons
        tk.Button(self.control_panel,
                text="Toggle Overlay",
                command=self.toggle_overlay).pack(pady=5)
        
        tk.Button(self.control_panel,
                text="Toggle Epic Mode",
                command=self.toggle_epic_mode).pack(pady=5)
        
        tk.Button(self.control_panel,
                text="Exit",
                command=self.shutdown).pack(pady=5)

    def toggle_overlay(self):
        """Toggle overlay visibility"""
        if self.root.state() == 'withdrawn':
            self.root.deiconify()
        else:
            self.root.withdraw()

    def toggle_epic_mode(self):
        """Toggle epic mode through the control panel"""
        with state_lock:
            current_state['epic_mode'] = not current_state['epic_mode']
        
        if current_state['epic_mode']:
            overlay_queue.put("EPIC_ON")
            print(f"{Fore.MAGENTA}Epic Mode: ON (via control panel){Style.RESET_ALL}")
        else:
            overlay_queue.put("EPIC_OFF")
            print(f"{Fore.MAGENTA}Epic Mode: OFF (via control panel){Style.RESET_ALL}")

    def shutdown(self):
        """Clean shutdown"""
        shutdown_event.set()
        self.root.quit()

    def update_display(self):
        """Update the overlay display"""
        try:
            # Process all pending messages
            while True:
                try:
                    message = overlay_queue.get_nowait()
                    
                    if message == "SHOW":
                        self.show_execute()
                    elif message == "HIDE":
                        self.hide_overlay()
                    elif isinstance(message, tuple) and message[0] == "PROGRESS":
                        self.update_progress(*message[1:])
                    elif message == "EPIC_ON":
                        self.epic_label.config(text="Epic: ON", fg="#FF5555")
                    elif message == "EPIC_OFF":
                        self.epic_label.config(text="Epic: OFF", fg="#AAAAAA")
                            
                except queue.Empty:
                    break
            
            # Schedule next update
            if not shutdown_event.is_set():
                self.root.after(50, self.update_display)
                
        except Exception as e:
            print(f"Overlay update error: {e}")
            if not shutdown_event.is_set():
                self.root.after(50, self.update_display)

    def show_execute(self):
        """Show execute indicator"""
        if not self.active:
            self.root.deiconify()
            self.progress.configure(style="execute.Horizontal.TProgressbar")
            self.label.config(text="EXECUTE NOW!", fg="#FF0000")
            self.active = True

    def hide_overlay(self):
        """Hide the overlay completely"""
        if self.active:
            self.root.withdraw()
            self.active = False

    def update_progress(self, damage_percent, remaining_hp):
        """Update progress bar with current state"""
        if not self.active:
            self.root.deiconify()
        
        self.progress["value"] = damage_percent * 100
        
        if damage_percent > 0.9:
            self.progress.configure(style="warning.Horizontal.TProgressbar")
            self.label.config(text=f"ALMOST READY ({int(remaining_hp)} HP)", fg="#FFA500")
        elif damage_percent > 0.7:
            self.progress.configure(style="ready.Horizontal.TProgressbar")
            self.label.config(text=f"APPROACHING ({int(remaining_hp)} HP)", fg="#4CAF50")
        else:
            self.progress.configure(style="default.Horizontal.TProgressbar")
            self.label.config(text=f"HP: {int(remaining_hp)}", fg="#FFFFFF")

    def start(self):
        """Start the overlay"""
        self.root.after(50, self.update_display)
        self.root.mainloop()

def main():
    print(f"{Fore.CYAN}Execute Assistant{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Initializing...{Style.RESET_ALL}")
    
    # Create and start overlay in main thread
    overlay = ExecuteOverlay()
    
    # Start worker threads
    threads = [
        threading.Thread(target=monitor_stats),
        threading.Thread(target=monitor_epic_toggle),
        threading.Thread(target=execute_indicator)
    ]
    
    for t in threads:
        t.daemon = True
        t.start()
    
    print(f"{Fore.GREEN}Running... Press Q to quit{Style.RESET_ALL}")
    
    try:
        overlay.start()
    except KeyboardInterrupt:
        shutdown_event.set()
    finally:
        print(f"{Fore.CYAN}Shutting down...{Style.RESET_ALL}")
        ocr_executor.shutdown(wait=False)
        shutdown_event.set()
        overlay.root.quit()
        sys.exit(0)

if __name__ == "__main__":
    main()