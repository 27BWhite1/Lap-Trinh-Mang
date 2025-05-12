# server.py (Phiên bản GUI - Hỗ trợ phục vụ tệp media cục bộ qua HTTP)
import socket
import threading
import json
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog # Thêm filedialog
import sys
import os # Thêm os để thao tác với đường dẫn tệp
import http.server # Thêm module HTTP server
import socketserver # Thêm socketserver cho HTTP server

# --- Cấu hình Giao thức ---
SERVER_IP = "192.168.1.139"    # Lắng nghe trên tất cả các giao diện mạng khả dụng (hoặc dùng "127.0.0.1" nếu chạy cục bộ)
PORT = 12345             # Cổng kết nối chính cho lệnh

# --- Cấu hình HTTP Server cục bộ ---
HTTP_SERVER_PORT = 8000 # Cổng riêng cho HTTP server phục vụ media
MEDIA_DIR = "media"     # Thư mục chứa các tệp media (video, ảnh)

# --- Biến toàn cục Server Core (được quản lý bởi các luồng) ---
clients = {}             # Dictionary để lưu trữ {client_id: client_socket}
client_names = {}        # Dictionary để lưu trữ {client_id: client_name}
lock = threading.Lock()  # Khóa để bảo vệ biến clients khi truy cập đồng thời

# --- Các hàm Server Core (đã điều chỉnh để tương tác với GUI) ---

# Hàm này sẽ được gọi từ luồng xử lý client để log tin nhắn vào GUI
def handle_client(client_socket, addr, log_func, update_list_func):
    log_func(f"Client mới kết nối từ: {addr}", "INFO")
    client_id = None # ID của client này

    try:
        buffer = ""
        while True:
            data = client_socket.recv(4096).decode('utf-8')
            if not data:
                log_func(f"Client {client_id if client_id else addr} đã ngắt kết nối.", "WARNING")
                break
            
            buffer += data
            while "\n" in buffer:
                message, _, buffer = buffer.partition('\n')
                if not message.strip():
                    continue

                try:
                    command = json.loads(message)
                    cmd_type = command.get("command")

                    if cmd_type == "CLIENT_REGISTER":
                        received_client_id = command.get("client_id")
                        received_client_name = command.get("client_name", received_client_id)

                        with lock:
                            if received_client_id in clients:
                                log_func(f"Client ID {received_client_id} đã tồn tại, kết nối mới sẽ ghi đè.", "WARNING")
                                # Đóng socket cũ nếu có
                                try:
                                    clients[received_client_id].close()
                                except:
                                    pass
                            clients[received_client_id] = client_socket
                            client_names[received_client_id] = received_client_name
                            client_id = received_client_id # Gán ID cho kết nối hiện tại
                        
                        log_func(f"Client {client_names.get(client_id, client_id)} (ID: {client_id}) đã đăng ký thành công.", "INFO")
                        send_acknowledgement(client_socket, "CLIENT_REGISTER", "SUCCESS", "Đăng ký thành công.", log_func)
                        update_list_func() # Cập nhật danh sách client trên GUI
                    elif cmd_type == "ACKNOWLEDGEMENT":
                        original_cmd_id = command.get("original_command_id", "N/A")
                        status = command.get("status", "N/A")
                        message_ack = command.get("message", "")
                        log_func(f"Nhận được ACK từ Client {client_names.get(client_id, client_id)} cho lệnh {original_cmd_id}: {status} - {message_ack}", "INFO")
                    else:
                        log_func(f"Nhận được lệnh không xác định từ Client {client_id}: {command}", "WARNING")
                        send_acknowledgement(client_socket, cmd_type, "FAILURE", "Lệnh không xác định.", log_func)

                except json.JSONDecodeError:
                    log_func(f"JSON không hợp lệ từ {client_id if client_id else addr}: {message}", "ERROR")
                    send_acknowledgement(client_socket, "UNKNOWN", "FAILURE", "JSON không hợp lệ.", log_func)
                except Exception as e:
                    log_func(f"Lỗi xử lý lệnh từ {client_id if client_id else addr}: {e}, Lệnh: {message}", "ERROR")
                    send_acknowledgement(command, "FAILURE", str(e), log_func) # Truyền command thay vì cmd_type

    except socket.error as e:
        log_func(f"Lỗi socket với Client {client_id if client_id else addr}: {e}", "ERROR")
    except Exception as e:
        log_func(f"Một lỗi không mong muốn đã xảy ra với Client {client_id if client_id else addr}: {e}", "ERROR")
    finally:
        if client_id:
            with lock:
                if client_id in clients and clients[client_id] == client_socket:
                    del clients[client_id]
                    if client_id in client_names:
                        del client_names[client_id]
                    log_func(f"Client {client_id} đã bị xóa khỏi danh sách.", "INFO")
            update_list_func() # Cập nhật danh sách client trên GUI khi ngắt kết nối
        client_socket.close()

# Hàm gửi acknowledgement (xác nhận) tới client
def send_acknowledgement(target_socket, original_command_id, status, message="", log_func=print):
    ack = {
        "command": "ACKNOWLEDGEMENT",
        "original_command_id": original_command_id,
        "status": status,
        "message": message
    }
    try:
        target_socket.sendall(json.dumps(ack).encode('utf-8') + b'\n')
    except Exception as e:
        log_func(f"Lỗi gửi ACK: {e}", "ERROR")

# Hàm gửi lệnh tới client cụ thể
def send_command_to_client(client_id_target, command_type, content_data, log_func=print):
    command = {
        "command": command_type,
        "content": content_data
    }
    message = json.dumps(command).encode('utf-8') + b'\n'

    with lock:
        target_socket = clients.get(client_id_target)
        if target_socket:
            try:
                target_socket.sendall(message)
                log_func(f"Đã gửi lệnh {command_type} tới client {client_names.get(client_id_target, client_id_target)}", "INFO")
                return True
            except Exception as e:
                log_func(f"Không thể gửi lệnh tới client {client_names.get(client_id_target, client_id_target)}: {e}", "ERROR")
                # Xóa client nếu socket không hoạt động
                if client_id_target in clients and clients[client_id_target] == target_socket:
                    del clients[client_id_target]
                    if client_id_target in client_names:
                        del client_names[client_id_target]
                return False
        else:
            log_func(f"Client {client_id_target} không trực tuyến hoặc không tồn tại.", "WARNING")
            return False

# Hàm lấy địa chỉ IP cục bộ của máy chủ (không phải loopback)
def get_local_ip():
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)) # Kết nối tới một địa chỉ bên ngoài (không gửi dữ liệu thực)
        local_ip = s.getsockname()[0]
        return local_ip
    except Exception:
        return "127.0.0.1" # Trở về loopback nếu không có kết nối mạng hoặc lỗi
    finally:
        if s:
            s.close()

# Lớp máy chủ HTTP cục bộ
class LocalHTTPServer:
    def __init__(self, host, port, directory, log_func):
        self.host = host
        self.port = port
        self.directory = directory
        self.log_func = log_func
        self.httpd = None
        self.server_thread = None

    def start(self):
        # Đảm bảo thư mục media tồn tại
        os.makedirs(self.directory, exist_ok=True)

        # Bắt giá trị directory từ phạm vi của LocalHTTPServer.start()
        # để nó có thể được sử dụng trong MyHandler
        handler_directory = self.directory 

        # Custom handler để ghi log yêu cầu HTTP
        class MyHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(handler_self, format, *args):
                # Chuyển log HTTP về hàm log_func của GUI
                self.log_func(f"HTTP: {format % args}", "INFO")
            
            def __init__(self, *args, **kwargs):
                # Thiết lập thư mục phục vụ cho SimpleHTTPRequestHandler
                # Truyền handler_directory đã được bắt vào hàm khởi tạo của lớp cha
                super().__init__(*args, directory=handler_directory, **kwargs) 

        self.log_func(f"Đang cố gắng khởi động máy chủ HTTP cục bộ tại {self.host}:{self.port} từ thư mục: {os.path.abspath(self.directory)}", "INFO")
        try:
            # Sử dụng TCPServer và chạy trong luồng riêng
            self.httpd = socketserver.TCPServer((self.host, self.port), MyHandler)
            self.server_thread = threading.Thread(target=self.httpd.serve_forever)
            self.server_thread.daemon = True # Luồng daemon sẽ tự thoát khi chương trình chính thoát
            self.server_thread.start()
            self.log_func(f"Máy chủ HTTP cục bộ đã khởi động tại {self.host}:{self.port}", "INFO")
            return True
        except Exception as e:
            self.log_func(f"Không thể khởi động máy chủ HTTP cục bộ: {e}", "CRITICAL")
            self.httpd = None
            return False

    def stop(self):
        if self.httpd:
            self.log_func("Đang tắt máy chủ HTTP cục bộ...", "INFO")
            self.httpd.shutdown() # Tắt máy chủ một cách nhẹ nhàng
            self.httpd.server_close() # Đóng socket server
            self.log_func("Máy chủ HTTP cục bộ đã dừng.", "INFO")
            self.httpd = None
            self.server_thread = None

# Lớp trợ giúp để chuyển hướng print() và lỗi ra widget Text của Tkinter
class TextRedirector(object):
    def __init__(self, widget, tag="stdout"):
        self.widget = widget
        self.tag = tag

    def write(self, str_val):
        self.widget.config(state='normal')
        self.widget.insert(tk.END, str_val, (self.tag,))
        self.widget.see(tk.END) # Cuộn đến cuối
        self.widget.config(state='disabled')

    def flush(self):
        pass # Bắt buộc phải có cho các đối tượng giống file

# Lớp chính của ứng dụng GUI Server
class ServerGUI:
    def __init__(self, master):
        self.master = master
        master.title("Network Display Server")
        master.geometry("900x750") # Tăng kích thước cửa sổ

        self.server_running = False
        self.server_socket = None
        self.http_server_instance = None
        self.local_server_ip = get_local_ip() # Lấy địa chỉ IP cục bộ của server

        self.create_widgets()

        # Chuyển hướng stdout/stderr vào log_text
        sys.stdout = TextRedirector(self.log_text, "stdout")
        sys.stderr = TextRedirector(self.log_text, "stderr")

    def create_widgets(self):
        # Khung chính
        self.main_frame = ttk.Frame(self.master, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Khung Client List (bên trái)
        self.client_frame = ttk.LabelFrame(self.main_frame, text="Kết nối Client", padding="10")
        self.client_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.client_list_label = ttk.Label(self.client_frame, text="Clients đang kết nối:")
        self.client_list_label.pack(pady=5)
        self.client_listbox = tk.Listbox(self.client_frame, height=15)
        self.client_listbox.pack(fill=tk.BOTH, expand=True)
        self.client_listbox.bind("<<ListboxSelect>>", self.on_client_listbox_select)
        
        self.refresh_clients_button = ttk.Button(self.client_frame, text="Làm mới danh sách Client", command=self.update_client_list)
        self.refresh_clients_button.pack(pady=5)
        
        # Khung Command (bên phải)
        self.command_frame = ttk.LabelFrame(self.main_frame, text="Gửi Lệnh", padding="10")
        self.command_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.selected_client_id_label = ttk.Label(self.command_frame, text="Gửi đến Client:")
        self.selected_client_id_label.pack(pady=5)
        self.selected_client_id = tk.StringVar()
        self.client_dropdown = ttk.Combobox(self.command_frame, textvariable=self.selected_client_id, state="readonly")
        self.client_dropdown.set("Chọn Client")
        self.client_dropdown.pack(pady=5)
        self.client_dropdown.bind("<<ComboboxSelected>>", self.on_client_select) # Có thể không cần thiết nếu dùng Listbox

        # Notebook cho các loại lệnh (Text, Image, Video)
        self.notebook = ttk.Notebook(self.command_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Tab Văn bản
        self.text_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.text_tab, text="Văn bản")
        self.text_input_label = ttk.Label(self.text_tab, text="Nội dung Văn bản:")
        self.text_input_label.pack(pady=5)
        self.text_content = tk.StringVar()
        self.text_entry = ttk.Entry(self.text_tab, textvariable=self.text_content, width=50)
        self.text_entry.pack(pady=5)
        self.send_text_button = ttk.Button(self.text_tab, text="Gửi Văn bản", command=self.send_text)
        self.send_text_button.pack(pady=5)

        # Tab Ảnh (Đã sửa đổi để hỗ trợ chọn tệp cục bộ)
        self.image_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.image_tab, text="Ảnh")
        self.image_url_label = ttk.Label(self.image_tab, text="URL Ảnh hoặc chọn tệp cục bộ:")
        self.image_url_label.pack(pady=5)
        self.image_url = tk.StringVar()
        self.image_url_entry = ttk.Entry(self.image_tab, textvariable=self.image_url, width=50)
        self.image_url_entry.pack(pady=5)
        self.browse_image_button = ttk.Button(self.image_tab, text="Chọn Tệp Ảnh Cục Bộ", command=self.browse_local_image)
        self.browse_image_button.pack(pady=5)
        self.image_mode_label = ttk.Label(self.image_tab, text="Chế độ hiển thị (fit, fill, stretch):")
        self.image_mode_label.pack(pady=5)
        self.image_mode = tk.StringVar(value="fit")
        self.image_mode_entry = ttk.Entry(self.image_tab, textvariable=self.image_mode, width=20)
        self.image_mode_entry.pack(pady=5)
        self.send_image_button = ttk.Button(self.image_tab, text="Gửi Ảnh", command=self.send_image)
        self.send_image_button.pack(pady=5)

        # Tab Video (Đã sửa đổi để hỗ trợ chọn tệp cục bộ)
        self.video_tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(self.video_tab, text="Video")
        self.video_url_label = ttk.Label(self.video_tab, text="URL Video hoặc chọn tệp cục bộ:")
        self.video_url_label.pack(pady=5)
        self.video_url = tk.StringVar()
        self.video_url_entry = ttk.Entry(self.video_tab, textvariable=self.video_url, width=50)
        self.video_url_entry.pack(pady=5)
        self.browse_video_button = ttk.Button(self.video_tab, text="Chọn Tệp Video Cục Bộ", command=self.browse_local_video)
        self.browse_video_button.pack(pady=5)
        self.video_loop = tk.BooleanVar()
        self.video_loop_check = ttk.Checkbutton(self.video_tab, text="Lặp lại (Loop)", variable=self.video_loop)
        self.video_loop_check.pack(pady=5)
        self.send_video_button = ttk.Button(self.video_tab, text="Gửi Video", command=self.send_video)
        self.send_video_button.pack(pady=5)

        # Các nút điều khiển Video (không nằm trong Notebook để dễ truy cập)
        self.video_control_frame = ttk.LabelFrame(self.command_frame, text="Điều khiển Video", padding="10")
        self.video_control_frame.pack(fill=tk.X, padx=5, pady=10)

        self.clear_button = ttk.Button(self.video_control_frame, text="Xóa Màn hình", command=self.clear_screen_command)
        self.clear_button.grid(row=0, column=0, padx=5, pady=5)
        self.play_button = ttk.Button(self.video_control_frame, text="Play", command=self.play_video)
        self.play_button.grid(row=0, column=1, padx=5, pady=5)
        self.pause_button = ttk.Button(self.video_control_frame, text="Pause", command=self.pause_video)
        self.pause_button.grid(row=0, column=2, padx=5, pady=5)
        self.stop_button = ttk.Button(self.video_control_frame, text="Stop", command=self.stop_video)
        self.stop_button.grid(row=0, column=3, padx=5, pady=5)

        self.seek_label = ttk.Label(self.video_control_frame, text="Tua (ms):")
        self.seek_label.grid(row=1, column=0, padx=5, pady=5)
        self.seek_time = tk.StringVar()
        self.seek_entry = ttk.Entry(self.video_control_frame, textvariable=self.seek_time, width=10)
        self.seek_entry.grid(row=1, column=1, padx=5, pady=5)
        self.seek_button = ttk.Button(self.video_control_frame, text="Tua", command=self.seek_video)
        self.seek_button.grid(row=1, column=2, padx=5, pady=5)

        self.volume_label = ttk.Label(self.video_control_frame, text="Âm lượng (0-100):")
        self.volume_label.grid(row=2, column=0, padx=5, pady=5)
        self.volume_val = tk.StringVar()
        self.volume_entry = ttk.Entry(self.video_control_frame, textvariable=self.volume_val, width=10)
        self.volume_entry.grid(row=2, column=1, padx=5, pady=5)
        self.volume_button = ttk.Button(self.video_control_frame, text="Đặt Âm lượng", command=self.set_volume)
        self.volume_button.grid(row=2, column=2, padx=5, pady=5)

        # KHUNG ĐIỀU KHIỂN SERVER (PHÍA DƯỚI CÙNG CỦA CỬA SỔ CHÍNH)
        self.server_control_frame = ttk.Frame(self.master, padding="10")
        self.server_control_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)
        self.start_server_button = ttk.Button(self.server_control_frame, text="Bắt đầu Server", command=self.start_server)
        self.start_server_button.pack(side=tk.LEFT, padx=10)
        self.stop_server_button = ttk.Button(self.server_control_frame, text="Dừng Server", command=self.stop_server, state=tk.DISABLED)
        self.stop_server_button.pack(side=tk.LEFT, padx=10)
        # Hiển thị IP cục bộ
        self.ip_label = ttk.Label(self.server_control_frame, text=f"IP của Server: {self.local_server_ip}:{PORT} (Lệnh)\nHTTP Server: {self.local_server_ip}:{HTTP_SERVER_PORT} (Media)", foreground="blue")
        self.ip_label.pack(side=tk.RIGHT, padx=10)


        # KHUNG LOG (PHÍA TRÊN KHUNG ĐIỀU KHIỂN SERVER)
        self.log_frame = ttk.LabelFrame(self.master, text="Log Máy Chủ", padding="10")
        self.log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.log_text = tk.Text(self.log_frame, height=10, state='disabled', wrap='word') # wrap='word' để tự xuống dòng
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_scrollbar = ttk.Scrollbar(self.log_frame, command=self.log_text.yview)
        self.log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=self.log_scrollbar.set)


    def on_client_listbox_select(self, event):
        # Khi chọn một client từ listbox, cập nhật dropdown
        selected_indices = self.client_listbox.curselection()
        if selected_indices:
            index = selected_indices[0]
            selected_text = self.client_listbox.get(index)
            # Trích xuất client_id từ chuỗi "ID: <client_id>, Tên: <client_name>"
            try:
                client_id_start = selected_text.find("ID: ") + 4
                client_id_end = selected_text.find(", Tên:")
                client_id = selected_text[client_id_start:client_id_end].strip()
                self.selected_client_id.set(client_id)
            except Exception as e:
                self.log_message(f"Lỗi khi đọc client_id từ listbox: {e}", "ERROR")


    def on_client_select(self, event):
        # Hàm này được gọi khi một mục trong Combobox được chọn.
        # Có thể dùng để thực hiện các tác vụ phụ trợ nếu cần.
        selected_id = self.selected_client_id.get()
        self.log_message(f"Đã chọn client: {selected_id}", "INFO")


    def log_message(self, message, level="INFO"):
        # Ghi log vào widget Text của GUI (thread-safe)
        self.master.after(0, self._insert_log, f"[{level}] {message}\n")

    def _insert_log(self, message):
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END) # Cuộn đến cuối
        self.log_text.config(state='disabled')

    def update_client_list(self):
        # Cập nhật danh sách client trên GUI (thread-safe)
        self.master.after(0, self._do_update_client_list)

    def _do_update_client_list(self):
        self.client_listbox.delete(0, tk.END)
        client_ids_for_dropdown = []
        with lock:
            for client_id, client_sock in clients.items():
                self.client_listbox.insert(tk.END, f"ID: {client_id}, Tên: {client_names.get(client_id, client_id)}")
                client_ids_for_dropdown.append(client_id)
        self.client_dropdown['values'] = client_ids_for_dropdown
        
        # Nếu không có client nào được chọn trong dropdown hoặc client đó đã ngắt kết nối, chọn client đầu tiên nếu có
        current_selected_id = self.selected_client_id.get()
        if current_selected_id not in client_ids_for_dropdown and client_ids_for_dropdown:
            self.selected_client_id.set(client_ids_for_dropdown[0])
        elif not client_ids_for_dropdown:
            self.selected_client_id.set("Chọn Client")


    def get_selected_client_id(self):
        selected_id = self.selected_client_id.get()
        if not selected_id or selected_id == "Chọn Client":
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn một client từ danh sách thả xuống.")
            return None
        return selected_id

    def browse_local_image(self):
        file_path = filedialog.askopenfilename(
            initialdir=os.path.join(os.getcwd(), MEDIA_DIR), # Bắt đầu từ thư mục media
            title="Chọn tệp ảnh",
            filetypes=(("Tệp ảnh", "*.png *.jpg *.jpeg *.gif *.bmp"), ("Tất cả tệp", "*.*"))
        )
        if file_path:
            self.set_local_media_url(file_path, self.image_url)

    def browse_local_video(self):
        file_path = filedialog.askopenfilename(
            initialdir=os.path.join(os.getcwd(), MEDIA_DIR), # Bắt đầu từ thư mục media
            title="Chọn tệp video",
            filetypes=(("Tệp video", "*.mp4 *.avi *.mov *.mov *.mkv *.webm"), ("Tất cả tệp", "*.*"))
        )
        if file_path:
            self.set_local_media_url(file_path, self.video_url)

    def set_local_media_url(self, file_path, target_StringVar):
        # Đảm bảo tệp nằm trong thư mục MEDIA_DIR
        # os.path.abspath(MEDIA_DIR) để có đường dẫn tuyệt đối của thư mục media
        abs_media_dir = os.path.abspath(MEDIA_DIR)
        abs_file_path = os.path.abspath(file_path)
        
        # Kiểm tra xem tệp có nằm trong thư mục media hay không
        # os.path.commonpath() sẽ trả về đường dẫn chung dài nhất
        if os.path.commonpath([abs_media_dir, abs_file_path]) != abs_media_dir:
             messagebox.showwarning(
                "Cảnh báo",
                f"Tệp '{os.path.basename(file_path)}' không nằm trong thư mục '{MEDIA_DIR}'.\n"
                f"Vui lòng di chuyển tệp vào thư mục '{abs_media_dir}' để máy chủ có thể phục vụ."
            )
             target_StringVar.set("") # Xóa nội dung nếu tệp không hợp lệ
             return

        # Tạo URL HTTP cục bộ. file_name cần được encode URL nếu có ký tự đặc biệt
        file_name = os.path.basename(file_path)
        # Có thể cần urllib.parse.quote để xử lý các ký tự đặc biệt trong tên tệp nếu có.
        # Ví dụ: from urllib.parse import quote
        # encoded_file_name = quote(file_name)
        
        local_url = f"http://{self.local_server_ip}:{HTTP_SERVER_PORT}/{file_name}"
        target_StringVar.set(local_url)
        self.log_message(f"Đã chọn tệp cục bộ: {file_path}. URL cục bộ: {local_url}", "INFO")


    def send_text(self):
        client_id = self.get_selected_client_id()
        if client_id:
            content = self.text_content.get().strip()
            if content:
                # Thay thế khoảng trắng bằng dấu gạch dưới cho mục đích hiển thị nếu cần
                # client có thể phải tự xử lý các ký tự này
                content_data = {"type": "plain", "text": content} 
                send_command_to_client(client_id, "DISPLAY_TEXT", content_data, self.log_message)
                self.text_content.set("") # Xóa ô nhập
            else:
                messagebox.showwarning("Cảnh báo", "Vui lòng nhập nội dung văn bản.")

    def send_image(self):
        client_id = self.get_selected_client_id()
        if client_id:
            image_url = self.image_url.get().strip()
            display_mode = self.image_mode.get().strip()
            if image_url:
                content_data = {"type": "url", "value": image_url, "display_mode": display_mode}
                send_command_to_client(client_id, "DISPLAY_IMAGE", content_data, self.log_message)
                # self.image_url.set("") # Có thể không xóa ô nhập để dễ test lại URL
            else:
                messagebox.showwarning("Cảnh báo", "Vui lòng nhập URL ảnh hoặc chọn tệp cục bộ.")

    def send_video(self):
        client_id = self.get_selected_client_id()
        if client_id:
            video_url = self.video_url.get().strip()
            loop = self.video_loop.get()
            if video_url:
                content_data = {"type": "url", "value": video_url, "loop": loop, "autoplay": True}
                send_command_to_client(client_id, "DISPLAY_VIDEO", content_data, self.log_message)
                # self.video_url.set("") # Có thể không xóa ô nhập để dễ test lại URL
            else:
                messagebox.showwarning("Cảnh báo", "Vui lòng nhập URL video hoặc chọn tệp cục bộ.")

    def clear_screen_command(self):
        client_id = self.get_selected_client_id()
        if client_id:
            send_command_to_client(client_id, "CLEAR_SCREEN", {}, self.log_message)

    def play_video(self):
        client_id = self.get_selected_client_id()
        if client_id:
            send_command_to_client(client_id, "VIDEO_PLAY", {}, self.log_message)

    def pause_video(self):
        client_id = self.get_selected_client_id()
        if client_id:
            send_command_to_client(client_id, "VIDEO_PAUSE", {}, self.log_message)

    def stop_video(self):
        client_id = self.get_selected_client_id()
        if client_id:
            send_command_to_client(client_id, "VIDEO_STOP", {}, self.log_message)

    def seek_video(self):
        client_id = self.get_selected_client_id()
        if client_id:
            try:
                time_ms = int(self.seek_time.get().strip())
                content_data = {"time_ms": time_ms}
                send_command_to_client(client_id, "VIDEO_SEEK", content_data, self.log_message)
                self.seek_time.set("") # Xóa ô nhập
            except ValueError:
                messagebox.showerror("Lỗi", "Thời gian tua phải là số nguyên (milliseconds).")

    def set_volume(self):
        client_id = self.get_selected_client_id()
        if client_id:
            try:
                volume_val = int(self.volume_val.get().strip())
                if not (0 <= volume_val <= 100):
                    raise ValueError("Âm lượng phải trong khoảng 0-100.")
                content_data = {"volume": volume_val}
                send_command_to_client(client_id, "VIDEO_VOLUME", content_data, self.log_message)
                self.volume_val.set("") # Xóa ô nhập
            except ValueError as e:
                messagebox.showerror("Lỗi", f"Âm lượng không hợp lệ: {e}")

    def start_server(self):
        if self.server_running:
            self.log_message("Máy chủ đã chạy rồi.", "WARNING")
            return

        # Khởi động HTTP Server trước
        self.http_server_instance = LocalHTTPServer(self.local_server_ip, HTTP_SERVER_PORT, MEDIA_DIR, self.log_message)
        if not self.http_server_instance.start():
            self.log_message("Không thể khởi động máy chủ HTTP cục bộ. Vui lòng kiểm tra cổng hoặc lỗi khác.", "CRITICAL")
            self.server_running = False
            self.start_server_button.config(state=tk.NORMAL)
            self.stop_server_button.config(state=tk.DISABLED)
            return # Thoát nếu HTTP server không khởi động được

        # Sau đó khởi động Server chính
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((SERVER_IP, PORT))
            self.server_socket.listen(5)
            self.log_message(f"Server chính đang lắng nghe tại {SERVER_IP}:{PORT}", "INFO")
            
            self.server_running = True
            self.start_server_button.config(state=tk.DISABLED)
            self.stop_server_button.config(state=tk.NORMAL)
            
            # Bắt đầu chấp nhận kết nối trong một luồng mới
            self.accept_thread = threading.Thread(target=self._accept_connections_thread)
            self.accept_thread.daemon = True # Đặt luồng là daemon để nó tự tắt khi ứng dụng đóng
            self.accept_thread.start()

            self.update_client_list() # Cập nhật danh sách client ban đầu
            # Bắt đầu kiểm tra định kỳ để cập nhật danh sách client (vì client có thể ngắt kết nối đột ngột)
            self.master.after(5000, self.poll_client_list_update)    

        except Exception as e:
            self.log_message(f"Không thể khởi động server chính: {e}", "CRITICAL")
            self.server_running = False
            self.start_server_button.config(state=tk.NORMAL)
            self.stop_server_button.config(state=tk.DISABLED)
            # Nếu server chính lỗi, cố gắng dừng HTTP server nếu đã khởi động
            if self.http_server_instance:
                self.http_server_instance.stop()

    def stop_server(self):
        if not self.server_running:
            self.log_message("Máy chủ chưa chạy.", "WARNING")
            return
        
        self.log_message("Đang tắt máy chủ...", "INFO")
        self.server_running = False # Đặt cờ dừng cho luồng chấp nhận kết nối
        self.start_server_button.config(state=tk.NORMAL)
        self.stop_server_button.config(state=tk.DISABLED)
        
        # Dừng HTTP server trước
        if self.http_server_instance:
            self.http_server_instance.stop()

        # Dừng server chính
        if self.server_socket:
            try:
                self.server_socket.shutdown(socket.SHUT_RDWR)
                self.server_socket.close()
            except OSError as e:
                self.log_message(f"Lỗi khi đóng socket server chính: {e}", "ERROR")
            self.server_socket = None

        # Đóng tất cả các kết nối client
        with lock:
            for client_id, sock in list(clients.items()): # Lặp qua một bản sao để tránh lỗi khi xóa phần tử
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                    sock.close()
                    del clients[client_id]
                    del client_names[client_id]
                    self.log_message(f"Đã đóng kết nối với client {client_id}", "INFO")
                except Exception as e:
                    self.log_message(f"Lỗi khi đóng kết nối client {client_id}: {e}", "ERROR")
        self.update_client_list() # Cập nhật danh sách client trên GUI


    def _accept_connections_thread(self):
        # Hàm này chạy trong một luồng riêng để chấp nhận các kết nối đến
        self.server_socket.settimeout(1.0) # Đặt timeout để có thể kiểm tra cờ self.server_running
        while self.server_running:
            try:
                client_socket, addr = self.server_socket.accept()
                # Truyền hàm log_message và update_list_func của GUI cho luồng xử lý client
                client_handler = threading.Thread(target=handle_client, args=(client_socket, addr, self.log_message, self.update_client_list))
                client_handler.daemon = True
                client_handler.start()
                self.update_client_list() # Cập nhật danh sách client sau khi có kết nối mới
            except socket.timeout:
                continue # Timeout, tiếp tục vòng lặp để kiểm tra cờ self.server_running
            except OSError as e:
                if self.server_running: # Chỉ ghi log lỗi nếu server vẫn đang chạy
                    self.log_message(f"Lỗi chấp nhận kết nối: {e}", "ERROR")
                break # Thoát vòng lặp nếu socket server bị đóng hoặc lỗi xảy ra
            except Exception as e:
                self.log_message(f"Lỗi không mong muốn khi chấp nhận kết nối: {e}", "ERROR")
                if not self.server_running: # Thoát nếu server đang dừng
                    break

    def poll_client_list_update(self):
        # Hàm này kiểm tra định kỳ để cập nhật danh sách client.
        # Nó giúp đảm bảo danh sách trên GUI được chính xác ngay cả khi client ngắt kết nối đột ngột.
        self.update_client_list()
        if self.server_running:
            self.master.after(5000, self.poll_client_list_update) # Kiểm tra mỗi 5 giây


# --- Thực thi Chính ---
if __name__ == "__main__":
    # Đảm bảo thư mục media tồn tại khi khởi chạy script
    os.makedirs(MEDIA_DIR, exist_ok=True)
    print(f"Thư mục media được phục vụ: {os.path.abspath(MEDIA_DIR)}")

    root = tk.Tk() # Tạo cửa sổ Tkinter chính
    app = ServerGUI(root) # Khởi tạo ứng dụng GUI
    root.mainloop() # Bắt đầu vòng lặp sự kiện của Tkinter

    # Đảm bảo các socket được đóng khi GUI bị đóng
    if app.server_running and app.server_socket:
        app.stop_server()