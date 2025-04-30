import cv2
import numpy as np
import pyautogui
import time

# Wait 5 seconds before capturing the screenshot
print("Starting in 5 seconds... arrange your screen as needed.")
time.sleep(5)

# Capture a full-screen screenshot
screenshot = pyautogui.screenshot()
img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
clone = img.copy()  # We'll use a clone to reset drawing if needed

# Global variables for mouse callback
refPt = []
drawing = False

def draw_rectangle(event, x, y, flags, param):
    global refPt, drawing, clone

    if event == cv2.EVENT_LBUTTONDOWN:
        refPt = [(x, y)]
        drawing = True

    elif event == cv2.EVENT_MOUSEMOVE and drawing:
        # Draw a temporary rectangle on a copy for live preview
        temp_img = clone.copy()
        cv2.rectangle(temp_img, refPt[0], (x, y), (0, 0, 255), 2)
        cv2.imshow("Draw Region", temp_img)

    elif event == cv2.EVENT_LBUTTONUP:
        refPt.append((x, y))
        drawing = False
        # Draw the final rectangle on the clone image
        cv2.rectangle(clone, refPt[0], refPt[1], (0, 0, 255), 2)
        cv2.imshow("Draw Region", clone)
        print(f"Region of interest - Top-left: {refPt[0]}, Bottom-right: {refPt[1]}")

# Create a window and bind the mouse callback function to it
cv2.namedWindow("Draw Region", cv2.WINDOW_NORMAL)
cv2.imshow("Draw Region", clone)
cv2.setMouseCallback("Draw Region", draw_rectangle)

print("Draw a rectangle on the screen with your mouse. Press 'c' to close the window.")
while True:
    key = cv2.waitKey(1) & 0xFF
    if key == ord("c"):
        break

cv2.destroyAllWindows()
