import customtkinter as ctk
import cv2
import mediapipe as mp
import pyvirtualcam
import numpy as np
import threading
from PIL import Image
import time

# --- Configuration ---
# You can adjust these settings easily here
APP_TITLE = "Bye Chat 👋 - Linux Edition"
WINDOW_SIZE = "900x700"
VIRTUAL_DEVICE_PATH = '/dev/video20'  # Make sure this matches your modprobe command
CAMERA_INDEX = 0                      # 0 is usually the default integrated webcam
FADE_SPEED = 0.04                     # Lower number = slower fade

# Appearance Settings
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class ByeChatApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title(APP_TITLE)
        self.geometry(WINDOW_SIZE)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Grid Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. Header
        self.lbl_title = ctk.CTkLabel(self, text="Bye Chat Generator", font=("Roboto", 24, "bold"))
        self.lbl_title.grid(row=0, column=0, pady=10)

        # 2. Preview Area
        self.lbl_video = ctk.CTkLabel(self, text="Camera disabled", fg_color="gray10", corner_radius=10)
        self.lbl_video.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")

        # 3. Controls Frame
        self.frame_controls = ctk.CTkFrame(self)
        self.frame_controls.grid(row=2, column=0, padx=20, pady=20, sticky="ew")

        # Buttons
        self.btn_start = ctk.CTkButton(self.frame_controls, text="Start Camera", command=self.toggle_camera, fg_color="green")
        self.btn_start.pack(side="left", padx=10, pady=10)

        self.btn_bg = ctk.CTkButton(self.frame_controls, text="Scan Background (5s)", command=self.capture_background_trigger, state="disabled")
        self.btn_bg.pack(side="left", padx=10, pady=10)

        self.btn_reset = ctk.CTkButton(self.frame_controls, text="Reset (I'm back!)", command=self.reset_visibility, fg_color="#1f538d", state="disabled")
        self.btn_reset.pack(side="left", padx=10, pady=10)

        self.lbl_status = ctk.CTkLabel(self.frame_controls, text="Status: Ready", text_color="gray")
        self.lbl_status.pack(side="right", padx=20)

        # --- Logic Variables ---
        self.running = False
        self.cap = None
        self.thread = None
        
        # Shared Data (Thread safety)
        self.current_frame = None 
        self.lock = threading.Lock() 

        # Image Processing Variables
        self.background_frame = None
        self.capturing_bg = False
        self.fading = False
        self.alpha_value = 1.0 
        
        # Initialize MediaPipe
        self.mp_hands = mp.solutions.hands
        self.mp_seg = mp.solutions.selfie_segmentation
        
        # Start GUI Update Loop
        self.update_gui_loop()

    def update_gui_loop(self):
        """
        Updates the GUI independently from the camera loop to prevent flickering.
        """
        if not self.running:
            # Check again in 100ms if running state changes
            self.after(100, self.update_gui_loop)
            return

        # Fetch the latest frame safely
        if self.current_frame is not None:
            with self.lock:
                frame_to_show = self.current_frame.copy()
            
            try:
                preview = cv2.cvtColor(frame_to_show, cv2.COLOR_BGR2RGBA)
                preview_pil = Image.fromarray(preview)
                ctk_img = ctk.CTkImage(light_image=preview_pil, dark_image=preview_pil, size=(640, 360))
                
                if self.running:
                    self.lbl_video.configure(image=ctk_img, text="")
            except Exception:
                pass
        
        # Schedule next update (~30 FPS for GUI)
        self.after(30, self.update_gui_loop)

    def toggle_camera(self):
        if not self.running:
            self.start_camera()
        else:
            self.stop_camera()

    def start_camera(self):
        if self.running: return
        self.running = True
        self.btn_start.configure(text="Stop", fg_color="red")
        self.btn_bg.configure(state="normal")
        self.lbl_status.configure(text="Starting...", text_color="yellow")
        
        self.thread = threading.Thread(target=self.video_processing_thread, daemon=True)
        self.thread.start()

    def stop_camera(self):
        self.running = False
        
        self.btn_start.configure(text="Start Camera", fg_color="green")
        self.btn_bg.configure(state="disabled")
        self.btn_reset.configure(state="disabled")
        self.lbl_status.configure(text="Stopping...", text_color="gray")
        
        try:
            self.lbl_video.configure(text="Camera stopped")
        except: 
            pass

    def reset_visibility(self):
        self.fading = False
        self.alpha_value = 1.0
        self.lbl_status.configure(text="Reset! Waiting for Peace sign ✌️", text_color="green")

    def on_close(self):
        self.running = False
        if self.cap: self.cap.release()
        self.destroy()

    def capture_background_trigger(self):
        def countdown():
            self.btn_bg.configure(state="disabled")
            for i in range(5, 0, -1):
                if not self.running: return
                self.lbl_status.configure(text=f"Move out! {i}...", text_color="orange")
                time.sleep(1)
            self.capturing_bg = True
            
        threading.Thread(target=countdown, daemon=True).start()

    def detect_peace_sign(self, hand_landmarks):
        # Y-Axis is inverted (0 is top of screen)
        # Check if Index & Middle fingers are extended (Tip higher than PIP joint)
        index_up = hand_landmarks.landmark[8].y < hand_landmarks.landmark[6].y
        middle_up = hand_landmarks.landmark[12].y < hand_landmarks.landmark[10].y
        # Check if Ring & Pinky are curled (Tip lower than PIP joint)
        ring_down = hand_landmarks.landmark[16].y > hand_landmarks.landmark[14].y
        pinky_down = hand_landmarks.landmark[20].y > hand_landmarks.landmark[18].y
        
        return index_up and middle_up and ring_down and pinky_down

    def video_processing_thread(self):
        self.cap = cv2.VideoCapture(CAMERA_INDEX)
        time.sleep(0.5) # Wait for cam to init

        if not self.cap.isOpened():
             self.lbl_status.configure(text=f"Error: Cannot open Camera {CAMERA_INDEX}", text_color="red")
             self.running = False
             return

        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        hands = self.mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)
        segmentation = self.mp_seg.SelfieSegmentation(model_selection=0)

        self.lbl_status.configure(text="Ready. Scan background!", text_color="yellow")

        try:
            with pyvirtualcam.Camera(width=w, height=h, fps=30, device=VIRTUAL_DEVICE_PATH, fmt=pyvirtualcam.PixelFormat.BGR) as cam:
                print(f"Virtual Stream active on: {cam.device}")
                
                while self.running:
                    ret, frame = self.cap.read()
                    if not ret: 
                        time.sleep(0.1)
                        continue

                    frame = cv2.flip(frame, 1)
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                    # --- 1. Background Capture ---
                    if self.capturing_bg:
                        bg_frames = []
                        for _ in range(5):
                             r, f = self.cap.read()
                             if r: bg_frames.append(cv2.flip(f, 1))
                        
                        if bg_frames:
                            self.background_frame = np.median(bg_frames, axis=0).astype(dtype=np.uint8)
                            self.reset_visibility()
                            self.capturing_bg = False
                            self.after(0, lambda: [
                                self.lbl_status.configure(text="Background OK! Waiting for Peace Sign", text_color="green"),
                                self.btn_bg.configure(state="normal"),
                                self.btn_reset.configure(state="normal")
                            ])
                        continue 

                    # --- 2. Detection Logic ---
                    is_peace = False
                    if self.background_frame is not None and not self.fading and self.alpha_value > 0.9:
                        hand_results = hands.process(rgb_frame)
                        if hand_results.multi_hand_landmarks:
                            for lm in hand_results.multi_hand_landmarks:
                                if self.detect_peace_sign(lm):
                                    is_peace = True
                                    break 

                    if is_peace:
                        self.fading = True
                        self.after(0, lambda: self.lbl_status.configure(text="BYE CHAT! 👋", text_color="cyan"))

                    # --- 3. Rendering & Fade ---
                    final_output = frame

                    if self.background_frame is not None:
                        if self.fading or self.alpha_value < 1.0:
                            if self.fading:
                                self.alpha_value -= FADE_SPEED
                                if self.alpha_value <= 0: 
                                    self.alpha_value = 0
                                    self.fading = False
                                    self.after(0, lambda: self.lbl_status.configure(text="Gone.", text_color="gray"))

                            seg_results = segmentation.process(rgb_frame)
                            mask = seg_results.segmentation_mask 
                            mask_3d = np.stack((mask,) * 3, axis=-1)
                            
                            # Create the ghost effect (blending current frame with stored background)
                            blended_ghost = cv2.addWeighted(frame, self.alpha_value, self.background_frame, 1.0 - self.alpha_value, 0)
                            
                            # Combine: Where mask detects person (>0.4), show ghost; otherwise show pure background
                            final_output = np.where(mask_3d > 0.4, blended_ghost, self.background_frame)

                    # Send to virtual camera
                    cam.send(final_output)
                    cam.sleep_until_next_frame()

                    # Update the shared frame variable for the GUI
                    with self.lock:
                        self.current_frame = final_output

        except Exception as e:
            print(f"Thread Error: {e}")
            try:
                self.lbl_status.configure(text="Error: Check Terminal", text_color="red")
            except: pass
        finally:
            if self.cap and self.cap.isOpened():
                self.cap.release()
            print("Physical Camera Released")

if __name__ == "__main__":
    app = ByeChatApp()
    app.mainloop()