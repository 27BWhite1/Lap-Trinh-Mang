import socket
import threading
import tkinter as tk
from tkinter import Label
import json
import os
import time
from PIL import Image, ImageTk
import io
import zlib # Để giải nén

# --- Cấu hình Client ---
SERVER_HOST = '192.168.43.163' # SỬA LẠI ĐỊA CHỈ IP CỦA SERVER KHI CHẠY THỰC TẾ
SERVER_PORT = 65432
BUFFER_SIZE = 65536 # Tăng buffer cho phù hợp với server
HOSTNAME = socket.gethostname()

# --- Biến toàn cục ---
root = None
display_widget = None # Label để hiển thị stream ảnh
client_socket = None
is_connected = False # Client đã kết nối TCP
is_confirmed = False # Server đã xác nhận
is_streaming = False # Cờ báo đang nhận stream hay không
listener_thread = None
stop_listener_flag = threading.Event() # Cờ để dừng luồng nghe khi thoát

# --- Hàm gửi tin nhắn JSON tới Server ---
def send_message_to_server(sock, message_dict):
    try:
        message = json.dumps(message_dict).encode('utf-8')
        message_length = len(message).to_bytes(4, byteorder='big')
        sock.sendall(message_length + message)
        # print(f"Đã gửi: {message_dict}")
        return True
    except (socket.error, BrokenPipeError, ConnectionResetError) as e:
        print(f"Lỗi mạng khi gửi tới server: {e}")
        handle_server_disconnection()
        return False
    except Exception as e: print(f"Lỗi gửi không xác định: {e}"); return False

# --- Hàm xử lý hiển thị ảnh stream (chạy trên Main Thread) ---
def update_display_from_stream(image_bytes):
    global display_widget
    if not display_widget or not root or not root.winfo_exists():
        return

    try:
        # Giải nén zlib
        decompressed_bytes = zlib.decompress(image_bytes)
        # Đọc ảnh từ BytesIO
        img_data = io.BytesIO(decompressed_bytes)
        img = Image.open(img_data)

        # Resize ảnh để vừa màn hình client (giữ tỷ lệ)
        window_width = root.winfo_width()
        window_height = root.winfo_height()
        img.thumbnail((window_width, window_height), Image.Resampling.LANCZOS)

        photo = ImageTk.PhotoImage(img)
        display_widget.config(image=photo, text="") # Hiển thị ảnh
        display_widget.image = photo # Giữ tham chiếu
    except zlib.error as e:
         print(f"Lỗi giải nén frame: {e}")
         # Có thể hiển thị lỗi lên màn hình client
         display_widget.config(text="Lỗi giải nén frame...", fg="red", image='')
         display_widget.image=None
    except Exception as e:
        print(f"Lỗi hiển thị frame stream: {e}")
        # Có thể hiển thị lỗi lên màn hình client
        display_widget.config(text=f"Lỗi hiển thị frame:\n{e}", fg="red", image='')
        display_widget.image=None

def clear_display():
     if display_widget:
          display_widget.config(text="", image='')
          display_widget.image = None

# --- Hàm lắng nghe lệnh và dữ liệu từ Server ---
def listen_to_server(sock):
    global is_connected, is_confirmed, is_streaming
    buffer = b""
    expected_data_len = None # Độ dài của frame ảnh hoặc tin nhắn JSON

    while not stop_listener_flag.is_set():
        try:
            data = sock.recv(BUFFER_SIZE)
            if not data:
                print("Server đã đóng kết nối.")
                handle_server_disconnection()
                break

            buffer += data

            while True: # Xử lý liên tục các tin nhắn/frames trong buffer
                if expected_data_len is None: # Chưa biết độ dài -> chờ header 4 bytes
                    if len(buffer) >= 4:
                        expected_data_len = int.from_bytes(buffer[:4], byteorder='big')
                        buffer = buffer[4:]
                        # print(f"Nhận header, chờ data dài: {expected_data_len}")
                    else:
                        break # Chưa đủ header

                if expected_data_len is not None and len(buffer) >= expected_data_len:
                    # Đã đủ dữ liệu cho 1 frame ảnh hoặc 1 tin nhắn JSON
                    payload = buffer[:expected_data_len]
                    buffer = buffer[expected_data_len:]
                    expected_data_len = None # Reset để chờ header tiếp theo

                    # Xử lý payload
                    if is_streaming:
                        # Nếu đang stream -> payload là dữ liệu ảnh nén
                        # print(f"Nhận frame ảnh, size: {len(payload)}")
                        if root: # Đảm bảo root còn tồn tại
                            # Lên lịch cập nhật GUI từ main thread
                            root.after(0, update_display_from_stream, payload)
                    else:
                        # Nếu không stream -> payload là tin nhắn JSON
                        try:
                            message = json.loads(payload.decode('utf-8'))
                            print(f"Nhận lệnh JSON: {message}")
                            msg_type = message.get("type")

                            if msg_type == "confirm":
                                is_confirmed = True
                                print("Kết nối đã được Server xác nhận.")
                                if root: root.after(0, lambda: root.title(f"Client Display - Đã kết nối - {HOSTNAME}"))
                                if display_widget: root.after(0, lambda: display_widget.config(text="Đã kết nối. Chờ nội dung...", fg="white"))

                            elif msg_type == "stream_start" and is_confirmed:
                                print("Nhận lệnh bắt đầu stream.")
                                is_streaming = True
                                if display_widget: root.after(0, clear_display) # Xóa text chờ

                            elif msg_type == "stream_stop":
                                print("Nhận lệnh dừng stream.")
                                is_streaming = False
                                if display_widget: root.after(0, lambda: display_widget.config(text="Stream đã kết thúc.", fg="white"))

                            # Xử lý các lệnh JSON khác nếu có (ví dụ: display text/image kiểu cũ nếu muốn kết hợp)

                        except json.JSONDecodeError:
                            print(f"Lỗi: Không thể giải mã JSON khi không ở chế độ stream: {payload[:100]}") # In 100 byte đầu
                        except Exception as e:
                            print(f"Lỗi xử lý JSON: {e}")
                else:
                     # Chưa đủ dữ liệu cho frame/tin nhắn hiện tại
                     break # Chờ nhận thêm

        except (ConnectionResetError, BrokenPipeError):
            print("Mất kết nối tới Server.")
            handle_server_disconnection()
            break
        except socket.timeout:
             print("Socket recv timeout?") # Không nên xảy ra với blocking socket
             time.sleep(0.1)
        except Exception as e:
            # Bắt các lỗi khác như lỗi khi root đã bị hủy
            if "main window" not in str(e).lower() and "application has been destroyed" not in str(e).lower():
                 print(f"Lỗi không xác định trong luồng lắng nghe: {e}")
            handle_server_disconnection()
            break

    print("Luồng lắng nghe đã dừng.")

# --- Hàm xử lý khi mất kết nối ---
def handle_server_disconnection():
    global is_connected, is_confirmed, is_streaming, client_socket
    was_connected = is_connected
    is_connected = False
    is_confirmed = False
    is_streaming = False
    if client_socket:
        try: client_socket.close()
        except: pass
        client_socket = None

    if was_connected: # Chỉ hiển thị nếu trước đó đã kết nối
        print("Đã đóng kết nối client socket.")
        if root and root.winfo_exists():
            root.after(0, update_ui_on_disconnect)

def update_ui_on_disconnect():
     if root and root.winfo_exists():
        root.title(f"Client Display - Đã ngắt kết nối - {HOSTNAME}")
        if display_widget:
            display_widget.config(text="Đã mất kết nối tới Server...", fg="red", image='')
            display_widget.image = None
        # Tạm thời không tự kết nối lại trong phiên bản stream này
        # print("Thử kết nối lại sau 5 giây...")
        # root.after(5000, try_reconnect)

# --- Hàm kết nối ban đầu ---
def connect_to_server():
    global client_socket, is_connected, is_confirmed, is_streaming, listener_thread
    if is_connected: return True # Đã kết nối rồi

    try:
        is_confirmed = False
        is_streaming = False
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # sock.settimeout(10.0) # Đặt timeout cho connect
        sock.connect((SERVER_HOST, SERVER_PORT))
        # sock.settimeout(None) # Bỏ timeout sau khi kết nối
        print(f"Đã kết nối TCP tới Server {SERVER_HOST}:{SERVER_PORT}")
        client_socket = sock
        is_connected = True

        connect_msg = {"type": "connect", "hostname": HOSTNAME}
        if not send_message_to_server(sock, connect_msg):
             handle_server_disconnection()
             return False

        # Khởi động luồng lắng nghe nếu chưa có hoặc đã dừng
        stop_listener_flag.clear() # Đảm bảo cờ dừng không bị set
        listener_thread = threading.Thread(target=listen_to_server, args=(sock,), daemon=True)
        listener_thread.start()
        return True

    except socket.timeout:
        print(f"Không thể kết nối tới server (timeout).")
        handle_server_disconnection()
        return False
    except socket.error as e:
        print(f"Không thể kết nối tới server {SERVER_HOST}:{SERVER_PORT} - {e}")
        handle_server_disconnection()
        return False
    except Exception as e:
        print(f"Lỗi không xác định khi kết nối: {e}")
        handle_server_disconnection()
        return False

# --- Hàm tạo GUI ---
def create_gui():
    global root, display_widget

    root = tk.Tk()
    root.title(f"Client Display - Đang kết nối - {HOSTNAME}")
    root.configure(bg="black") # Nền đen cho toàn bộ cửa sổ

    display_widget = Label(root, text="Đang kết nối tới Server...", font=("Arial", 24),
                           fg="white", bg="black", justify="center")
    display_widget.pack(fill=tk.BOTH, expand=True)

    root.attributes('-fullscreen', True)
    root.bind('<Escape>', lambda e: exit_fullscreen()) # Thoát fullscreen và đóng app

    if not connect_to_server():
        if display_widget: display_widget.config(text=f"Không thể kết nối tới Server\n{SERVER_HOST}:{SERVER_PORT}", fg="red")
        # Tạm thời không tự kết nối lại
        # print("Sẽ thử lại sau 5 giây...")
        # root.after(5000, try_reconnect)

    def on_closing_client():
        print("Đóng ứng dụng Client...")
        stop_listener_flag.set() # Báo cho luồng nghe dừng lại
        handle_server_disconnection() # Đóng socket
        if listener_thread and listener_thread.is_alive():
             print("Đang chờ luồng lắng nghe kết thúc...")
             listener_thread.join(timeout=1.0) # Chờ tối đa 1s
        root.destroy()

    def exit_fullscreen(event=None):
         print("Thoát fullscreen và đóng ứng dụng...")
         root.attributes('-fullscreen', False)
         # Đợi một chút rồi đóng để tránh lỗi đồ họa
         root.after(100, on_closing_client)


    root.protocol("WM_DELETE_WINDOW", on_closing_client) # Xử lý khi nhấn nút X (nếu không fullscreen)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("Ctrl+C detected, closing client...")
        on_closing_client()

# --- Chạy chương trình ---
if __name__ == "__main__":
    create_gui()
    print("Ứng dụng Client Stream đã thoát.")