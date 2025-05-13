import socket
import threading
from tkinter import *
from tkinter import massagebox
import urllib.request
import subprocess
import sys
import json
import os
import time
from PIL import Image, ImageTk
import io

# --- Cấu hình Giao thức ---
SERVER_IP = "192.168.1.139" 
PORT = 12345           

# --- Biến toàn cục ---
client_socket = None
client_id = "laptop_a" 
client_name = "Laptop A" 

current_content_frame = None 
current_image_tk = None 
reconnect_delay = 5 

# Biến toàn cục để quản lý VLC Player (cho phát nhúng)
vlc_instance = None
vlc_player = None

# --- Chức năng GUI ---
def log_message(message, level="INFO"): 
    print(f"[{level}] [Client Log] {message}") 

def create_fullscreen_window():
    global root, display_canvas
    root = Tk()
    root.title(f"Màn hình Hiển thị Khách - {client_name}")
    
    root.attributes('-fullscreen', True)
    root.bind("<Escape>", lambda event: root.destroy()) 
    root.config(bg="black")

    display_canvas = Canvas(root, bg="black", highlightthickness=0)
    display_canvas.pack(fill=BOTH, expand=YES)

    root.bind("<Configure>", on_resize)

    clear_screen() 

def on_resize(event):
    # Khi cửa sổ Tkinter thay đổi kích thước, VLC thường tự điều chỉnh.
    # Không cần code cụ thể ở đây trừ khi bạn muốn kiểm soát chính xác vị trí/kích thước của video.
    if vlc_player:
        pass


def clear_screen():
    global current_content_frame, vlc_player
    if current_content_frame:
        current_content_frame.destroy()
        current_content_frame = None
    display_canvas.delete("all") 
    display_canvas.config(bg="black") 
    
    # Dừng và giải phóng trình phát VLC khi chuyển nội dung hoặc xóa màn hình
    if vlc_player:
        log_message("Đang dừng và giải phóng trình phát VLC nhúng.", "INFO")
        vlc_player.stop()
        vlc_player.release() # Giải phóng tài nguyên của trình phát hiện tại
        vlc_player = None


def display_text(text_data):
    clear_screen() 
    text = text_data.get("text", "")
    font_size = text_data.get("font_size", 36)
    font_color = text_data.get("font_color", "#FFFFFF")
    bg_color = text_data.get("background_color", "#000000")

    display_canvas.config(bg=bg_color)
    
    canvas_width = display_canvas.winfo_width()
    canvas_height = display_canvas.winfo_height()
    
    if canvas_width <= 1 or canvas_height <= 1:
        root.after(100, lambda: display_text(text_data))
        return

    display_canvas.create_text(
        canvas_width / 2, canvas_height / 2,
        text=text,
        font=("Arial", font_size),
        fill=font_color,
        anchor="center",
        justify="center",
        width=canvas_width - 20 
    )
    log_message("Đã hiển thị văn bản.", "INFO")


def display_image(image_data):
    clear_screen() 
    image_source_type = image_data.get("type")
    image_value = image_data.get("value")
    display_mode = image_data.get("display_mode", "fit")

    if image_source_type == "url":
        try:
            log_message(f"Đang tải ảnh từ URL: {image_value}", "INFO")
            with urllib.request.urlopen(image_value) as url:
                raw_data = url.read()
            image = Image.open(io.BytesIO(raw_data))
            render_image_on_canvas(image, display_mode)
        except Exception as e:
            log_message(f"Lỗi tải ảnh từ URL: {e}", "ERROR")
            display_canvas.create_text(
                display_canvas.winfo_width() / 2, display_canvas.winfo_height() / 2,
                text=f"Không thể tải ảnh: {e}",
                font=("Arial", 18),
                fill="red",
                anchor="center"
            )
    else:
        log_message("Loại nguồn ảnh không xác định hoặc không được hỗ trợ.", "WARNING")

def render_image_on_canvas(image, display_mode):
    global current_image_tk
    canvas_width = display_canvas.winfo_width()
    canvas_height = display_canvas.winfo_height()

    if canvas_width <= 1 or canvas_height <= 1:
        root.after(100, lambda: render_image_on_canvas(image, display_mode))
        return

    img_width, img_height = image.size

    if display_mode == "fit":
        ratio_w = canvas_width / img_width
        ratio_h = canvas_height / img_height
        scale_ratio = min(ratio_w, ratio_h)
        new_width = int(img_width * scale_ratio)
        new_height = int(img_height * scale_ratio)
        image = image.resize((new_width, new_height), Image.LANCZOS)
        x = (canvas_width - new_width) / 2
        y = (canvas_height - new_height) / 2
    elif display_mode == "fill":
        ratio_w = canvas_width / img_width
        ratio_h = canvas_height / img_height
        scale_ratio = max(ratio_w, ratio_h)
        new_width = int(img_width * scale_ratio)
        new_height = int(img_height * scale_ratio)
        image = image.resize((new_width, new_height), Image.LANCZOS)
        x = (canvas_width - new_width) / 2
        y = (canvas_height - new_height) / 2
    elif display_mode == "stretch":
        image = image.resize((canvas_width, canvas_height), Image.LANCZOS)
        x = 0
        y = 0
    else: 
        ratio_w = canvas_width / img_width
        ratio_h = canvas_height / img_height
        scale_ratio = min(ratio_w, ratio_h)
        new_width = int(img_width * scale_ratio)
        new_height = int(img_height * scale_ratio)
        image = image.resize((new_width, new_height), Image.LANCZOS)
        x = (canvas_width - new_width) / 2
        y = (canvas_height - new_height) / 2

    current_image_tk = ImageTk.PhotoImage(image)
    log_message("Đã hiển thị ảnh.", "INFO")
    display_canvas.create_image(x, y, anchor="nw", image=current_image_tk)

def display_video(video_data):
    global vlc_instance, vlc_player
    clear_screen() 

    video_source_type = video_data.get("type")
    video_value = video_data.get("value")
    loop = video_data.get("loop", False)

    if video_source_type == "url":
        log_message(f"Đang cố gắng phát video từ URL (nhúng vào cửa sổ Tkinter): {video_value}", "INFO")
        try:
            if vlc_instance is None:
                vlc_instance = vlc.Instance()

            if vlc_player: 
                vlc_player.stop()
                vlc_player.release()
            vlc_player = vlc_instance.media_player_new()
            
            window_id = display_canvas.winfo_id()

            if sys.platform.startswith('win'): 
                vlc_player.set_hwnd(window_id)
            elif sys.platform.startswith('linux'): 
                vlc_player.set_xwindow(window_id)
            elif sys.platform.startswith('darwin'): 
                log_message("Nhúng video trên macOS rất phức tạp và có thể không hoạt động trực tiếp với Tkinter. Vui lòng thử xem nó có hoạt động không. Nếu không, hãy cân nhắc quay lại phương pháp phát VLC riêng biệt cho macOS.", "WARNING")
                vlc_player.set_nsobject(window_id) 
            else:
                log_message("Hệ điều hành không được hỗ trợ cho phát video nhúng trực tiếp vào cửa sổ Tkinter.", "ERROR")
                display_canvas.create_text(
                    display_canvas.winfo_width() / 2, display_canvas.winfo_height() / 2,
                    text="Hệ điều hành không được hỗ trợ cho phát video nhúng.",
                    font=("Arial", 18),
                    fill="red",
                    anchor="center",
                    justify="center"
                )
                return

            media_options = []
            if loop:
                media_options.append(":input-repeat=65535") 

            media = vlc_instance.media_new(video_value, *media_options)
            vlc_player.set_media(media)
            vlc_player.play()
            
            log_message("Video đang được phát trực tiếp trên màn hình khách (nhúng VLC).", "INFO")

        except Exception as e:
            log_message(f"Lỗi phát video nhúng: {e}. Đảm bảo VLC và thư viện python-vlc đã được cài đặt và VLC có thể truy cập tệp/URL.", "ERROR")
            display_canvas.create_text(
                display_canvas.winfo_width() / 2, display_canvas.winfo_height() / 2,
                text=f"Lỗi phát video nhúng: {e}\n(VLC hoặc lỗi tệp video)",
                font=("Arial", 18),
                fill="red",
                anchor="center",
                justify="center"
            )
    else:
        log_message("Loại nguồn video không xác định hoặc không được hỗ trợ cho phát nhúng.", "WARNING")

# --- HÀM MỚI ĐỂ ĐIỀU KHIỂN VIDEO ---
def handle_video_play():
    global vlc_player
    if vlc_player:
        log_message("Đang tiếp tục phát video.", "INFO")
        vlc_player.play()
    else:
        log_message("Không có video nào đang phát để tiếp tục.", "WARNING")

def handle_video_pause():
    global vlc_player
    if vlc_player and vlc_player.is_playing():
        log_message("Đang tạm dừng phát video.", "INFO")
        vlc_player.pause()
    else:
        log_message("Không có video nào đang phát để tạm dừng.", "WARNING")

def handle_video_stop():
    global vlc_player
    if vlc_player:
        log_message("Đang dừng phát video và xóa màn hình.", "INFO")
        vlc_player.stop()
        clear_screen() # Dừng video và xóa màn hình client
    else:
        log_message("Không có video nào đang phát để dừng.", "WARNING")

def handle_video_seek(time_ms):
    global vlc_player
    if vlc_player and vlc_player.is_playing():
        log_message(f"Đang tua video đến {time_ms}ms.", "INFO")
        vlc_player.set_time(time_ms)
    else:
        log_message("Không có video nào đang phát để tua.", "WARNING")

def handle_video_volume(volume):
    global vlc_player
    if vlc_player:
        log_message(f"Đang đặt âm lượng video thành {volume}.", "INFO")
        vlc_player.audio_set_volume(volume)
    else:
        log_message("Không có video nào đang phát để điều chỉnh âm lượng.", "WARNING")


# --- Logic Giao tiếp Máy khách ---
def connect_to_server():
    global client_socket
    if client_socket:
        try:
            client_socket.close()
        except:
            pass 
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        log_message(f"Đang kết nối tới máy chủ tại {SERVER_IP}:{PORT}...", "INFO")
        client_socket.connect((SERVER_IP, PORT))
        log_message(f"Đã kết nối tới máy chủ tại {SERVER_IP}:{PORT}", "INFO")
        
        registration_msg = {
            "command": "CLIENT_REGISTER",
            "client_id": client_id,
            "client_name": client_name
        }
        client_socket.sendall(json.dumps(registration_msg).encode('utf-8') + b'\n')
        ack = client_socket.recv(4096).decode('utf-8') 
        ack_data = json.loads(ack.strip()) 
        if ack_data.get("status") == "SUCCESS":
            log_message("Đã đăng ký thành công với máy chủ.", "INFO")
            listen_thread = threading.Thread(target=listen_for_commands)
            listen_thread.daemon = True 
            listen_thread.start()
        else:
            log_message(f"Đăng ký máy chủ thất bại: {ack_data.get('message')}", "ERROR")
            messagebox.showerror("Lỗi kết nối", f"Đăng ký máy chủ thất bại: {ack_data.get('message')}")
            sys.exit(1) 

    except ConnectionRefusedError:
        log_message(f"Kết nối bị từ chối. Máy chủ đang chạy tại {SERVER_IP}:{PORT} không?", "ERROR")
        root.after(reconnect_delay * 1000, connect_to_server) 
    except Exception as e:
        log_message(f"Lỗi khi kết nối tới máy chủ: {e}", "ERROR")
        root.after(reconnect_delay * 1000, connect_to_server) 

def listen_for_commands():
    global client_socket
    buffer = ""
    while True:
        try:
            data = client_socket.recv(4096).decode('utf-8')
            if not data:
                log_message("Máy chủ đã ngắt kết nối.", "WARNING")
                break 
            
            buffer += data
            while "\n" in buffer: 
                message, _, buffer = buffer.partition('\n')
                if not message.strip(): 
                    continue
                try:
                    command = json.loads(message)
                    process_command(command)
                    send_acknowledgement(command, "SUCCESS")
                except json.JSONDecodeError:
                    log_message(f"JSON không hợp lệ nhận được: {message}", "ERROR")
                    send_acknowledgement({"command": "UNKNOWN", "original_command_id": "N/A"}, "FAILURE", "JSON không hợp lệ")
                except Exception as e:
                    log_message(f"Lỗi xử lý lệnh: {e}, Lệnh: {message}", "ERROR")
                    send_acknowledgement(command, "FAILURE", str(e))

        except socket.error as e:
            log_message(f"Lỗi socket: {e}. Đang cố gắng kết nối lại...", "ERROR")
            break 
        except Exception as e:
            log_message(f"Một lỗi không mong muốn đã xảy ra: {e}", "ERROR")
            break 
    
    log_message("Luồng lắng nghe đã kết thúc. Đang cố gắng kết nối lại...", "INFO")
    reconnect_to_server()

def process_command(command):
    cmd_type = command.get("command")
    content_data = command.get("content")

    log_message(f"Đã nhận lệnh: {cmd_type}", "INFO")

    if cmd_type == "DISPLAY_TEXT":
        root.after(0, lambda: display_text(content_data))
    elif cmd_type == "DISPLAY_IMAGE":
        root.after(0, lambda: display_image(content_data))
    elif cmd_type == "DISPLAY_VIDEO":
        root.after(0, lambda: display_video(content_data)) 
    elif cmd_type == "CLEAR_SCREEN":
        root.after(0, clear_screen)
    # --- XỬ LÝ LỆNH ĐIỀU KHIỂN VIDEO MỚI ---
    elif cmd_type == "VIDEO_PLAY":
        root.after(0, handle_video_play)
    elif cmd_type == "VIDEO_PAUSE":
        root.after(0, handle_video_pause)
    elif cmd_type == "VIDEO_STOP":
        root.after(0, handle_video_stop)
    elif cmd_type == "VIDEO_SEEK":
        time_ms = content_data.get("time_ms")
        root.after(0, lambda: handle_video_seek(time_ms))
    elif cmd_type == "VIDEO_VOLUME":
        volume_val = content_data.get("volume")
        root.after(0, lambda: handle_video_volume(volume_val))
    # --- HẾT XỬ LÝ LỆNH MỚI ---
    elif cmd_type == "ACKNOWLEDGEMENT":
        log_message(f"Nhận được ACK từ Server cho lệnh {command.get('original_command_id')}: {command.get('status')} - {command.get('message')}", "INFO")
    else:
        log_message(f"Lệnh không xác định: {cmd_type}", "WARNING")

def send_acknowledgement(original_command, status, message=""):
    ack = {
        "command": "ACKNOWLEDGEMENT",
        "original_command_id": original_command.get("command", "N/A"), 
        "status": status,
        "message": message
    }
    try:
        client_socket.sendall(json.dumps(ack).encode('utf-8') + b'\n')
    except Exception as e:
        log_message(f"Lỗi gửi ACK: {e}", "ERROR")

def reconnect_to_server():
    global client_socket
    if client_socket:
        try:
            client_socket.close()
        except:
            pass
    log_message(f"Đang cố gắng kết nối lại sau {reconnect_delay} giây...", "INFO")
    root.after(reconnect_delay * 1000, connect_to_server)


# --- Thực thi Chính ---
if __name__ == "__main__":
    if len(sys.argv) > 1:
        client_id = sys.argv[1]
        client_name = client_id 
    if len(sys.argv) > 2:
        SERVER_IP = sys.argv[2] 

    try:
        subprocess.run(
            ["vlc", "--version"], 
            capture_output=True, 
            check=True, 
            creationflags=subprocess.CREATE_NO_WINDOW, 
            stdin=subprocess.DEVNULL
        )
        log_message("Đã tìm thấy VLC. Sẽ sử dụng nó để phát video nhúng.", "INFO")
    except (subprocess.CalledProcessError, FileNotFoundError):
        log_message("Không tìm thấy VLC. Phát video nhúng sẽ không hoạt động. Vui lòng cài đặt VLC và đảm bảo nó có trong PATH của hệ thống.", "ERROR")
        sys.exit(1) 

    create_fullscreen_window() 
    threading.Thread(target=connect_to_server, daemon=True).start() 
    root.mainloop()

    if vlc_player:
        vlc_player.stop()
        vlc_player.release()
    if vlc_instance:
        vlc_instance.release()
