# vit_share.py - REDESIGNED MODERN UI (FIXED)
# A peer-to-peer file sharing application with enhanced UI/UX for students
# Professional, clean, and intuitive design

import socket
import threading
import os
import json
import time
import sys
import shutil
import uuid
import tempfile
from tkinter import messagebox

try:
    import customtkinter
    import tkinterdnd2
    import qrcode
    from PIL import Image
except ImportError:
    print("Error: Required libraries are missing.")
    print("Please install them by running:")
    print("pip install customtkinter tkinterdnd2 qrcode Pillow")
    sys.exit(1)

# --- Configuration ---
TCP_PORT = 65432
UDP_PORT = 65431
QR_CONNECT_PORT = 65433
BROADCAST_MAGIC = "c0d3-p2p-share-v1"
PEER_TIMEOUT = 30

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_FOLDER_NAME = "P2P File Sharer Data"
APP_FOLDER_PATH = os.path.join(SCRIPT_DIR, APP_FOLDER_NAME)

SHARE_DIR = os.path.join(APP_FOLDER_PATH, "sharable")
DOWNLOAD_DIR = os.path.join(APP_FOLDER_PATH, "downloads")

BUFFER_SIZE = 16 * 1048576
FOLDER_TAG = " [Folder]"

# Modern Color Palette
COLORS = {
    'bg_primary': '#0F1419',
    'bg_secondary': '#1A1F2E',
    'bg_tertiary': '#252D3D',
    'accent_blue': '#3B82F6',
    'accent_purple': '#8B5CF6',
    'accent_green': '#10B981',
    'accent_red': '#EF4444',
    'text_primary': '#F9FAFB',
    'text_secondary': '#9CA3AF',
    'text_muted': '#6B7280',
    'border': '#374151',
    'hover': '#1F2937'
}

# --- Backend Logic Class ---
class P2PFileSharerBackend:
    def __init__(self, nickname, log_callback, 
                 send_progress_callback, send_status_callback, send_active_callback,
                 receive_progress_callback, receive_status_callback, receive_active_callback,
                 transfer_request_callback):
        self.nickname = nickname
        self.peers = {}
        self.peers_lock = threading.Lock()
        self.running = True
        self.log_callback = log_callback
        self.send_progress_callback = send_progress_callback
        self.send_status_callback = send_status_callback
        self.send_active_callback = send_active_callback
        self.receive_progress_callback = receive_progress_callback
        self.receive_status_callback = receive_status_callback
        self.receive_active_callback = receive_active_callback
        self.transfer_request_callback = transfer_request_callback
        self.active_transfers = {}
        self.transfer_lock = threading.Lock()
        self.current_send_id = None
        self.current_receive_id = None
        self.setup_directories()

    def setup_directories(self):
        if not os.path.exists(APP_FOLDER_PATH):
            os.makedirs(APP_FOLDER_PATH)
        for directory in [SHARE_DIR, DOWNLOAD_DIR]:
            if not os.path.exists(directory):
                os.makedirs(directory)

    def log(self, message):
        if self.log_callback:
            self.log_callback(message)

    def broadcast_presence(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            local_ip = self.get_local_ip()
            message = json.dumps({
                "magic": BROADCAST_MAGIC, 
                "nickname": self.nickname, 
                "ip": local_ip, 
                "device_type": "desktop"
            })
            
            self.log(f"Broadcasting from {local_ip} on port {UDP_PORT}")
            
            while self.running:
                try:
                    for broadcast_addr in ['255.255.255.255', '<broadcast>']:
                        try:
                            s.sendto(message.encode('utf-8'), (broadcast_addr, UDP_PORT))
                        except Exception:
                            pass
                except Exception as e:
                    self.log(f"Broadcast error: {e}")
                time.sleep(3)

    def listen_for_peers(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind(('', UDP_PORT))
            s.settimeout(1.0)
            
            self.log(f"Listening for peers on UDP port {UDP_PORT}")
            
            while self.running:
                try:
                    data, addr = s.recvfrom(1024)
                    message = json.loads(data.decode('utf-8'))
                    
                    if message.get("magic") == BROADCAST_MAGIC:
                        peer_nickname = message.get("nickname")
                        peer_ip = message.get("ip")
                        device_type = message.get("device_type", "unknown")
                        
                        if peer_nickname != self.nickname:
                            with self.peers_lock:
                                is_new = peer_nickname not in self.peers
                                self.peers[peer_nickname] = {
                                    'ip': peer_ip,
                                    'last_seen': time.time(),
                                    'device_type': device_type,
                                    'qr_connected': self.peers.get(peer_nickname, {}).get('qr_connected', False)
                                }
                                if is_new:
                                    self.log(f"Discovered peer: {peer_nickname} ({device_type}) at {peer_ip}")
                
                except socket.timeout:
                    continue
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    if self.running:
                        self.log(f"Peer listen error: {e}")
            
            s.close()
        except Exception as e:
            self.log(f"Failed to start peer listener: {e}")

    def cleanup_stale_peers(self):
        while self.running:
            time.sleep(5)
            current_time = time.time()
            with self.peers_lock:
                stale_peers = [
                    nickname for nickname, info in self.peers.items()
                    if current_time - info['last_seen'] > PEER_TIMEOUT 
                    and not info.get('qr_connected', False)
                ]
                for nickname in stale_peers:
                    del self.peers[nickname]
                    self.log(f"Peer {nickname} timed out")

    def get_peer_dict(self):
        with self.peers_lock:
            return {name: info['ip'] for name, info in self.peers.items()}

    def file_server(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            local_ip = self.get_local_ip()
            s.bind((local_ip, TCP_PORT))
            s.listen(5)
            s.settimeout(1.0)
            
            self.log(f"File server listening on {local_ip}:{TCP_PORT}")
            
            while self.running:
                try:
                    conn, addr = s.accept()
                    self.log(f"Incoming connection from {addr[0]}")
                    threading.Thread(target=self.handle_item_receive, args=(conn, addr), daemon=True).start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.log(f"Accept error: {e}")
            
            s.close()
        except Exception as e:
            self.log(f"File server error: {e}")

    def handle_item_receive(self, conn, addr):
        transfer_id = str(uuid.uuid4())
        filepath = ""
        metadata = {}
        with self.transfer_lock:
            self.active_transfers[transfer_id] = {'cancel': False, 'socket': conn}
        try:
            with conn:
                conn.settimeout(10.0)
                metadata_bytes = b''
                while self.running:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    metadata_bytes += chunk
                    if b'\n' in metadata_bytes:
                        parts = metadata_bytes.split(b'\n', 1)
                        metadata_bytes = parts[0]
                        remaining_data = parts[1] if len(parts) > 1 else b''
                        break
                
                if not metadata_bytes:
                    self.log(f"No metadata received from {addr[0]}")
                    return

                try:
                    metadata = json.loads(metadata_bytes.decode('utf-8'))
                    self.log(f"Received metadata: {metadata}")
                except json.JSONDecodeError as e:
                    self.log(f"Invalid JSON metadata from {addr[0]}: {e}")
                    return
                
                if metadata.get('type') == 'qr_handshake':
                    self.log(f"Detected QR handshake from {addr[0]}")
                    peer_nickname = metadata.get('nickname')
                    device_type = metadata.get('device_type', 'android')
                    
                    if peer_nickname:
                        with self.peers_lock:
                            self.peers[peer_nickname] = {
                                'ip': addr[0],
                                'last_seen': time.time() + 300,
                                'device_type': device_type,
                                'qr_connected': True
                            }
                        self.log(f"QR Handshake: Added peer '{peer_nickname}' ({device_type}) at {addr[0]}")
                        
                        our_info = {
                            'type': 'qr_handshake_response',
                            'nickname': self.nickname,
                            'ip': self.get_local_ip(),
                            'device_type': 'desktop',
                            'status': 'connected'
                        }
                        conn.sendall((json.dumps(our_info) + '\n').encode('utf-8'))
                    return
                
                if 'filename' not in metadata or 'filesize' not in metadata:
                    self.log(f"Missing required fields in metadata from {addr[0]}")
                    return
                
                result_container = {'accepted': False}
                confirmation_event = threading.Event()
                self.transfer_request_callback(metadata, result_container, confirmation_event)
                confirmation_event.wait()

                if not result_container.get('accepted'):
                    conn.sendall(b'REJECT\n')
                    return
                
                conn.sendall(b'ACCEPT\n')
                
                self.receive_active_callback(True)
                filename = os.path.basename(metadata['filename'])
                filesize = metadata['filesize']
                item_type = metadata.get('type', 'file')
                filepath = os.path.join(DOWNLOAD_DIR, filename)
                
                received_bytes = 0
                last_update = time.time()
                
                with open(filepath, 'wb') as f:
                    if remaining_data:
                        f.write(remaining_data)
                        received_bytes += len(remaining_data)

                    while received_bytes < filesize:
                        bytes_to_read = min(BUFFER_SIZE, filesize - received_bytes)
                        bytes_read = conn.recv(bytes_to_read)
                        if not bytes_read:
                            break
                        f.write(bytes_read)
                        received_bytes += len(bytes_read)
                        
                        current_time = time.time()
                        if current_time - last_update > 0.2:
                            progress = received_bytes / filesize
                            mb_received = received_bytes / 1048576
                            mb_total = filesize / 1048576
                            message = f"{filename}\n{mb_received:.1f}/{mb_total:.1f} MB"
                            self.receive_progress_callback(progress, message)
                            last_update = current_time
                
                if received_bytes == filesize:
                    self.receive_progress_callback(1.0, f"{filename}\nCompleted!")
                    self.log(f"'{filename}' received successfully.")
                    if item_type == 'directory':
                        try:
                            shutil.unpack_archive(filepath, DOWNLOAD_DIR)
                            self.log(f"Folder '{filename}' unpacked.")
                        except Exception as e:
                            self.log(f"Error unpacking folder: {e}")
                        finally:
                            if os.path.exists(filepath):
                                os.remove(filepath)
                else:
                    raise IOError("File transfer incomplete.")
        
        except Exception as e:
            self.log(f"Receive failed: {e}")
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception:
                    pass
        finally:
            with self.transfer_lock:
                if transfer_id in self.active_transfers:
                    del self.active_transfers[transfer_id]
            self.receive_active_callback(False)

    def send_item(self, peer_nickname, item_name):
        peer_dict = self.get_peer_dict()
        if peer_nickname not in peer_dict:
            self.log(f"Peer '{peer_nickname}' not found.")
            return
        peer_ip = peer_dict[peer_nickname]
        item_path = os.path.join(SHARE_DIR, item_name)
        if not os.path.exists(item_path):
            self.log(f"Item '{item_name}' not found.")
            return
        
        is_directory = os.path.isdir(item_path)
        temp_zip_path = None
        try:
            if is_directory:
                temp_dir = tempfile.gettempdir()
                temp_zip_base = os.path.join(temp_dir, item_name)
                temp_zip_path = shutil.make_archive(base_name=temp_zip_base, format='zip', root_dir=SHARE_DIR, base_dir=item_name)
                filepath_to_send = temp_zip_path
                item_type = 'directory'
            else:
                filepath_to_send = item_path
                item_type = 'file'

            filesize = os.path.getsize(filepath_to_send)
            filename = os.path.basename(filepath_to_send)
            metadata = {"filename": filename, "filesize": filesize, "type": item_type, "sender_nickname": self.nickname}
            
            self.log(f"Connecting to {peer_nickname} at {peer_ip}:{TCP_PORT}")
            
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect((peer_ip, TCP_PORT))
                s.sendall((json.dumps(metadata) + '\n').encode('utf-8'))
                
                response_file = s.makefile('rb')
                response = response_file.readline().strip()

                if response != b'ACCEPT':
                    self.log(f"Transfer rejected by {peer_nickname}.")
                    return

                self.send_active_callback(True)
                sent_bytes = 0
                last_update = time.time()
                
                with open(filepath_to_send, 'rb') as f:
                    while True:
                        bytes_read = f.read(BUFFER_SIZE)
                        if not bytes_read:
                            break
                        s.sendall(bytes_read)
                        sent_bytes += len(bytes_read)
                        
                        current_time = time.time()
                        if current_time - last_update > 0.2:
                            progress = sent_bytes / filesize
                            mb_sent = sent_bytes / 1048576
                            mb_total = filesize / 1048576
                            message = f"{item_name} to {peer_nickname}\n{mb_sent:.1f}/{mb_total:.1f} MB"
                            self.send_progress_callback(progress, message)
                            last_update = current_time
                
                self.send_progress_callback(1.0, f"{item_name}\nCompleted!")
                self.log(f"'{item_name}' sent to {peer_nickname}.")

        except socket.timeout:
            self.log(f"Connection timeout while sending to {peer_nickname}.")
        except Exception as e:
            self.log(f"Send failed for '{item_name}': {e}")
        finally:
            if temp_zip_path and os.path.exists(temp_zip_path):
                try:
                    os.remove(temp_zip_path)
                except Exception:
                    pass
            self.send_active_callback(False)

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            s.connect(('8.8.8.8', 80))
            IP = s.getsockname()[0]
            s.close()
            return IP
        except:
            try:
                hostname = socket.gethostname()
                IP = socket.gethostbyname(hostname)
                if not IP.startswith('127.'):
                    return IP
            except:
                pass
            return '127.0.0.1'

    def start_services(self):
        self.log("Backend services started.")
        self.log(f"Device name: {self.nickname}")
        self.log(f"Local IP: {self.get_local_ip()}")
        threading.Thread(target=self.broadcast_presence, daemon=True).start()
        threading.Thread(target=self.listen_for_peers, daemon=True).start()
        threading.Thread(target=self.cleanup_stale_peers, daemon=True).start()
        threading.Thread(target=self.file_server, daemon=True).start()
        # FIX 1 of 2: The following line was added to start the QR server thread.
        threading.Thread(target=self.qr_connect_server, daemon=True).start()

    # FIX 2 of 2: The entire qr_connect_server method was added below.
    def qr_connect_server(self):
        """Listen for QR-based peer connections"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            local_ip = self.get_local_ip()
            s.bind((local_ip, QR_CONNECT_PORT))
            s.listen(5)
            s.settimeout(1.0)
            
            self.log(f"QR Connect server listening on {local_ip}:{QR_CONNECT_PORT}")
            
            while self.running:
                try:
                    conn, addr = s.accept()
                    self.log(f"QR connection received from {addr[0]}")
                    threading.Thread(target=self.handle_qr_connection, args=(conn, addr), daemon=True).start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.log(f"QR accept error: {e}")
            
            s.close()
        except Exception as e:
            self.log(f"QR Connect server error: {e}")
    
    def handle_qr_connection(self, conn, addr):
        try:
            with conn:
                conn.settimeout(5.0)
                
                our_info = {
                    'nickname': self.nickname,
                    'ip': self.get_local_ip(),
                    'device_type': 'desktop',
                    'status': 'ready'
                }
                conn.sendall((json.dumps(our_info) + '\n').encode('utf-8'))
                self.log(f"Sent our info to {addr[0]}")
                
                data = b''
                while b'\n' not in data and len(data) < 4096:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                
                if data:
                    try:
                        peer_info = json.loads(data.decode('utf-8').strip())
                        self.log(f"Received peer info: {peer_info}")
                        
                        peer_nickname = peer_info.get('nickname')
                        peer_ip = peer_info.get('ip', addr[0])
                        device_type = peer_info.get('device_type', 'android')
                        
                        if peer_nickname:
                            with self.peers_lock:
                                self.peers[peer_nickname] = {
                                    'ip': peer_ip,
                                    'last_seen': time.time() + 300,
                                    'device_type': device_type,
                                    'qr_connected': True
                                }
                            self.log(f"QR Connect: Added peer '{peer_nickname}' ({device_type}) at {peer_ip}")
                    except json.JSONDecodeError as e:
                        self.log(f"Invalid JSON from {addr[0]}: {e}")
                
        except socket.timeout:
            self.log(f"QR connection from {addr[0]} timed out")
        except Exception as e:
            self.log(f"QR connection handler error from {addr[0]}: {e}")

    def stop_services(self):
        self.log("Shutting down...")
        self.running = False

# --- Modern GUI Class ---
class App(customtkinter.CTk, tkinterdnd2.TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = tkinterdnd2.TkinterDnD._require(self)
        self.qr_window = None
        self.backend = None

    def on_closing(self):
        if messagebox.askokcancel("Quit", "Do you want to quit VIT Share?"):
            if self.backend:
                self.backend.stop_services()
            self.destroy()

    def create_gradient_frame(self, parent):
        frame = customtkinter.CTkFrame(parent, corner_radius=12, fg_color=COLORS['bg_secondary'], 
                                      border_width=1, border_color=COLORS['border'])
        return frame

    def create_action_button(self, parent, text, command, color='accent_blue', width=140):
        btn = customtkinter.CTkButton(
            parent, text=text, command=command,
            font=("Inter", 13, "bold"),
            fg_color=COLORS[color],
            hover_color=self.adjust_color(COLORS[color], -20),
            corner_radius=8,
            height=38,
            width=width
        )
        return btn
    
    def adjust_color(self, hex_color, brightness_offset):
        hex_color = hex_color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        r = max(0, min(255, r + brightness_offset))
        g = max(0, min(255, g + brightness_offset))
        b = max(0, min(255, b + brightness_offset))
        return f'#{r:02x}{g:02x}{b:02x}'

    def setup_ui(self):
        self.title(f"VIT Share - {socket.gethostname()}")
        self.geometry("1100x750")
        customtkinter.set_appearance_mode("dark")
        
        self.configure(fg_color=COLORS['bg_primary'])
        
        # Configure grid layout
        self.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(0, weight=1)  # Main container
        self.grid_rowconfigure(1, weight=0)  # Progress container
        self.grid_rowconfigure(2, weight=1)  # Log container

        # MAIN CONTENT
        main_container = customtkinter.CTkFrame(self, fg_color="transparent")
        main_container.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=15, pady=(15, 0))
        main_container.grid_columnconfigure(0, weight=2)
        main_container.grid_columnconfigure(1, weight=3)
        main_container.grid_rowconfigure(0, weight=1)

        # LEFT PANEL - PEERS
        peers_container = self.create_gradient_frame(main_container)
        peers_container.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        peers_container.grid_columnconfigure(0, weight=1)
        peers_container.grid_rowconfigure(1, weight=1)
        
        peers_header = customtkinter.CTkFrame(peers_container, fg_color="transparent", height=50)
        peers_header.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))
        
        customtkinter.CTkLabel(
            peers_header, 
            text="Connected Devices",
            font=("Inter", 18, "bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left")
        
        self.peer_count_label = customtkinter.CTkLabel(
            peers_header,
            text="0",
            font=("Inter", 12, "bold"),
            text_color=COLORS['text_muted'],
            fg_color=COLORS['bg_tertiary'],
            corner_radius=12,
            width=30, height=24
        )
        self.peer_count_label.pack(side="left", padx=10)
        
        self.peers_list_frame = customtkinter.CTkScrollableFrame(
            peers_container, 
            fg_color=COLORS['bg_tertiary'],
            corner_radius=8,
            scrollbar_button_color=COLORS['border'],
            scrollbar_button_hover_color=COLORS['text_muted']
        )
        self.peers_list_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        self.peer_vars = {}
        
        qr_button_frame = customtkinter.CTkFrame(peers_container, fg_color="transparent")
        qr_button_frame.grid(row=2, column=0, sticky="ew", padx=15, pady=(0, 15))
        
        qr_connect_btn = customtkinter.CTkButton(
            qr_button_frame,
            text="Show My QR Code",
            command=self.show_qr_code,
            font=("Inter", 13, "bold"),
            fg_color=COLORS['accent_purple'],
            hover_color=self.adjust_color(COLORS['accent_purple'], -20),
            corner_radius=8,
            height=45
        )
        qr_connect_btn.pack(fill="x", pady=5)

        # RIGHT PANEL - FILES
        files_container = self.create_gradient_frame(main_container)
        files_container.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        files_container.grid_columnconfigure(0, weight=1)
        files_container.grid_rowconfigure(1, weight=1)
        
        files_header = customtkinter.CTkFrame(files_container, fg_color="transparent")
        files_header.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))
        
        customtkinter.CTkLabel(
            files_header,
            text="My Files",
            font=("Inter", 18, "bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left")
        
        self.file_count_label = customtkinter.CTkLabel(
            files_header,
            text="0 items",
            font=("Inter", 12),
            text_color=COLORS['text_muted']
        )
        self.file_count_label.pack(side="left", padx=10)
        
        drop_zone_frame = customtkinter.CTkFrame(files_container, fg_color=COLORS['bg_tertiary'], corner_radius=8)
        drop_zone_frame.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 10))
        drop_zone_frame.grid_columnconfigure(0, weight=1)
        drop_zone_frame.grid_rowconfigure(0, weight=1)
        
        self.files_list_frame = customtkinter.CTkScrollableFrame(
            drop_zone_frame,
            fg_color="transparent",
            scrollbar_button_color=COLORS['border'],
            scrollbar_button_hover_color=COLORS['text_muted']
        )
        self.files_list_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.files_list_frame.drop_target_register(tkinterdnd2.DND_FILES)
        self.files_list_frame.dnd_bind('<<Drop>>', self.handle_drop)
        self.file_vars = {}
        
        self.drop_hint = customtkinter.CTkFrame(self.files_list_frame, fg_color=COLORS['bg_secondary'], 
                                                corner_radius=8, border_width=2, 
                                                border_color=COLORS['border'])
        self.drop_hint.pack(fill="both", expand=True, padx=20, pady=40)
        
        customtkinter.CTkLabel(
            self.drop_hint,
            text="Drag & Drop Files Here",
            font=("Inter", 16, "bold"),
            text_color=COLORS['text_secondary']
        ).pack(pady=(40, 10))
        
        customtkinter.CTkLabel(
            self.drop_hint,
            text="or use the buttons below to add files and folders",
            font=("Inter", 11),
            text_color=COLORS['text_muted']
        ).pack(pady=(0, 40))
        
        button_frame = customtkinter.CTkFrame(files_container, fg_color="transparent")
        button_frame.grid(row=2, column=0, sticky="ew", padx=15, pady=(0, 10))
        button_frame.grid_columnconfigure((0, 1, 2), weight=1)
        
        self.create_action_button(button_frame, "Add Files", self.add_files_dialog, 'accent_blue').grid(row=0, column=0, padx=5, sticky="ew")
        self.create_action_button(button_frame, "Add Folder", self.add_folder_dialog, 'accent_blue').grid(row=0, column=1, padx=5, sticky="ew")
        self.create_action_button(button_frame, "Delete", self.delete_selected_items, 'accent_red').grid(row=0, column=2, padx=5, sticky="ew")
        
        self.send_btn = customtkinter.CTkButton(
            files_container, text="Send Selected Items",
            command=self.send_selected_items,
            font=("Inter", 15, "bold"),
            fg_color=COLORS['accent_green'],
            hover_color=self.adjust_color(COLORS['accent_green'], -20),
            corner_radius=8, height=50
        )
        self.send_btn.grid(row=3, column=0, sticky="ew", padx=15, pady=(5, 15))

        # PROGRESS SECTION
        progress_container = customtkinter.CTkFrame(self, fg_color="transparent")
        progress_container.grid(row=1, column=0, columnspan=2, sticky="ew", padx=15, pady=15)
        progress_container.grid_columnconfigure((0, 1), weight=1)
        
        send_card = self.create_gradient_frame(progress_container)
        send_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        
        send_header = customtkinter.CTkFrame(send_card, fg_color="transparent")
        send_header.pack(fill="x", padx=20, pady=(15, 5))
        
        customtkinter.CTkLabel(
            send_header, text="Sending",
            font=("Inter", 14, "bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left")
        
        self.send_status_indicator = customtkinter.CTkLabel(
            send_header, text="●",
            font=("Inter", 20),
            text_color=COLORS['text_muted']
        )
        self.send_status_indicator.pack(side="right")
        
        self.send_progress_label = customtkinter.CTkLabel(
            send_card, text="Idle",
            font=("Inter", 11),
            text_color=COLORS['text_secondary'],
            anchor="w"
        )
        self.send_progress_label.pack(fill="x", padx=20, pady=(0, 5))
        
        self.send_progress_bar = customtkinter.CTkProgressBar(
            send_card,
            progress_color=COLORS['accent_blue'],
            fg_color=COLORS['bg_tertiary'],
            corner_radius=4, height=8
        )
        self.send_progress_bar.pack(fill="x", padx=20, pady=(0, 15))
        self.send_progress_bar.set(0)
        
        receive_card = self.create_gradient_frame(progress_container)
        receive_card.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        
        receive_header = customtkinter.CTkFrame(receive_card, fg_color="transparent")
        receive_header.pack(fill="x", padx=20, pady=(15, 5))
        
        customtkinter.CTkLabel(
            receive_header, text="Receiving",
            font=("Inter", 14, "bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left")
        
        self.receive_status_indicator = customtkinter.CTkLabel(
            receive_header, text="●",
            font=("Inter", 20),
            text_color=COLORS['text_muted']
        )
        self.receive_status_indicator.pack(side="right")
        
        self.receive_progress_label = customtkinter.CTkLabel(
            receive_card, text="Idle",
            font=("Inter", 11),
            text_color=COLORS['text_secondary'],
            anchor="w"
        )
        self.receive_progress_label.pack(fill="x", padx=20, pady=(0, 5))
        
        self.receive_progress_bar = customtkinter.CTkProgressBar(
            receive_card,
            progress_color=COLORS['accent_green'],
            fg_color=COLORS['bg_tertiary'],
            corner_radius=4, height=8
        )
        self.receive_progress_bar.pack(fill="x", padx=20, pady=(0, 15))
        self.receive_progress_bar.set(0)

        # ACTIVITY LOG
        log_container = self.create_gradient_frame(self)
        log_container.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=15, pady=(0, 15))
        log_container.grid_columnconfigure(0, weight=1)
        log_container.grid_rowconfigure(1, weight=1)
        
        log_header = customtkinter.CTkFrame(log_container, fg_color="transparent")
        log_header.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 10))
        
        customtkinter.CTkLabel(
            log_header, text="Activity Log",
            font=("Inter", 16, "bold"),
            text_color=COLORS['text_primary']
        ).pack(side="left")
        
        clear_btn = customtkinter.CTkButton(
            log_header, text="Clear",
            command=self.clear_log,
            font=("Inter", 11),
            fg_color="transparent",
            hover_color=COLORS['hover'],
            text_color=COLORS['text_secondary'],
            width=70, height=28
        )
        clear_btn.pack(side="right")
        
        self.log_text = customtkinter.CTkTextbox(
            log_container,
            font=("Consolas", 10),
            fg_color=COLORS['bg_tertiary'],
            text_color=COLORS['text_secondary'],
            wrap="word",
            state="disabled"
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def show_qr_code(self):
        if self.qr_window and self.qr_window.winfo_exists():
            self.qr_window.focus()
            return

        ip_address = self.backend.get_local_ip()
        if not ip_address or ip_address == '127.0.0.1':
            messagebox.showerror("Network Error", "Could not get a valid IP address.")
            return

        self.qr_window = customtkinter.CTkToplevel(self)
        self.qr_window.title("Connect via QR Code")
        self.qr_window.geometry("360x480")
        self.qr_window.configure(fg_color=COLORS['bg_primary'])
        self.qr_window.transient(self)
        self.qr_window.resizable(False, False)
        
        header = customtkinter.CTkFrame(self.qr_window, fg_color=COLORS['bg_secondary'], corner_radius=0)
        header.pack(fill="x", padx=0, pady=0)
        
        customtkinter.CTkLabel(
            header,
            text="Scan to Connect",
            font=("Inter", 20, "bold"),
            text_color=COLORS['text_primary']
        ).pack(pady=20)
        
        qr_frame = customtkinter.CTkFrame(self.qr_window, fg_color="white", corner_radius=12)
        qr_frame.pack(padx=30, pady=20)
        
        # --- MODIFICATIONS FOR BETTER SCANNING ---
        # Increased border size and changed fill_color to "black" for max contrast
        qr = qrcode.QRCode(version=1, box_size=10, border=4) 
        qr.add_data(ip_address)
        qr.make(fit=True)
        
        # Using standard black and white
        qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
        # --- END MODIFICATIONS ---

        ctk_img = customtkinter.CTkImage(light_image=qr_img, dark_image=qr_img, size=(280, 280))
        
        qr_label = customtkinter.CTkLabel(qr_frame, image=ctk_img, text="")
        qr_label.image = ctk_img
        qr_label.pack(padx=10, pady=10) # Reduced padding to account for larger border in QR
        
        ip_frame = customtkinter.CTkFrame(self.qr_window, fg_color=COLORS['bg_secondary'], corner_radius=8)
        ip_frame.pack(fill="x", padx=30, pady=(0, 20))
        
        customtkinter.CTkLabel(
            ip_frame,
            text="IP Address",
            font=("Inter", 11),
            text_color=COLORS['text_muted']
        ).pack(pady=(15, 5))
        
        customtkinter.CTkLabel(
            ip_frame,
            text=ip_address,
            font=("Consolas", 16, "bold"),
            text_color=COLORS['accent_blue']
        ).pack(pady=(0, 15))
        
        customtkinter.CTkLabel(
            self.qr_window,
            text="Open VIT Share on your mobile device\nand scan this QR code to connect",
            font=("Inter", 11),
            text_color=COLORS['text_secondary'],
            justify="center"
        ).pack(pady=(0, 20))

    def setup_backend(self):
        self.backend = P2PFileSharerBackend(
            nickname=socket.gethostname(), 
            log_callback=self.add_log,
            send_progress_callback=self.update_send_progress,
            send_status_callback=self.update_send_status,
            send_active_callback=self.set_send_active,
            receive_progress_callback=self.update_receive_progress,
            receive_status_callback=self.update_receive_status,
            receive_active_callback=self.set_receive_active,
            transfer_request_callback=self.show_transfer_request
        )
        self.backend.start_services()
        self.update_peer_list()
        self.update_sharable_files_list()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def add_log(self, message):
        self.after(0, self._insert_log, message)

    def _insert_log(self, message):
        self.log_text.configure(state="normal")
        timestamp = time.strftime('%H:%M:%S')
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def update_send_progress(self, progress, message):
        self.after(0, self._update_send_progress, progress, message)

    def _update_send_progress(self, progress, message):
        self.send_progress_bar.set(progress)
        self.send_progress_label.configure(text=message)
        
        if progress > 0 and progress < 1:
            self.send_status_indicator.configure(text_color=COLORS['accent_blue'])
        else:
            self.send_status_indicator.configure(text_color=COLORS['text_muted'])

    def update_send_status(self, status, error=None):
        if error:
            self.add_log(f"Send error: {error}")
        else:
            self.add_log(status)

    def set_send_active(self, is_active):
        if not is_active:
            self.after(2000, lambda: (
                self.send_progress_bar.set(0), 
                self.send_progress_label.configure(text="Idle"),
                self.send_status_indicator.configure(text_color=COLORS['text_muted'])
            ))

    def update_receive_progress(self, progress, message):
        self.after(0, self._update_receive_progress, progress, message)

    def _update_receive_progress(self, progress, message):
        self.receive_progress_bar.set(progress)
        self.receive_progress_label.configure(text=message)
        
        if progress > 0 and progress < 1:
            self.receive_status_indicator.configure(text_color=COLORS['accent_green'])
        else:
            self.receive_status_indicator.configure(text_color=COLORS['text_muted'])

    def update_receive_status(self, status, error=None):
        if error:
            self.add_log(f"Receive error: {error}")
        else:
            self.add_log(status)

    def set_receive_active(self, is_active):
        if not is_active:
            self.after(2000, lambda: (
                self.receive_progress_bar.set(0), 
                self.receive_progress_label.configure(text="Idle"),
                self.receive_status_indicator.configure(text_color=COLORS['text_muted'])
            ))

    def show_transfer_request(self, metadata, result_container, confirmation_event):
        self.after(0, self._show_prompt_and_get_response, metadata, result_container, confirmation_event)

    def _show_prompt_and_get_response(self, metadata, result_container, confirmation_event):
        try:
            sender = metadata.get('sender_nickname', 'Unknown peer')
            item = metadata.get('filename', 'unknown item')
            size_bytes = metadata.get('filesize', 0)
            size_str = f"{size_bytes / 1e6:.2f} MB" if size_bytes > 1e6 else f"{size_bytes / 1e3:.1f} KB"
            
            dialog = customtkinter.CTkToplevel(self)
            dialog.title("Incoming Transfer")
            dialog.geometry("370x290")
            dialog.configure(fg_color=COLORS['bg_primary'])
            dialog.transient(self)
            dialog.resizable(False, False)
            
            dialog.update_idletasks()
            x = (dialog.winfo_screenwidth() // 2) - (400 // 2)
            y = (dialog.winfo_screenheight() // 2) - (250 // 2)
            dialog.geometry(f"+{x}+{y}")
            
            result_container['accepted'] = False
            
            def accept():
                result_container['accepted'] = True
                dialog.destroy()
                confirmation_event.set()
            
            def reject():
                result_container['accepted'] = False
                dialog.destroy()
                confirmation_event.set()
            
            dialog.protocol("WM_DELETE_WINDOW", reject)
            
            content_frame = customtkinter.CTkFrame(dialog, fg_color=COLORS['bg_secondary'], corner_radius=12)
            content_frame.pack(fill="both", expand=True, padx=20, pady=20)
            
            customtkinter.CTkLabel(
                content_frame,
                text="Incoming Transfer",
                font=("Inter", 18, "bold"),
                text_color=COLORS['text_primary']
            ).pack(pady=(20, 10))
            
            customtkinter.CTkLabel(
                content_frame,
                text=f"{sender} wants to send:",
                font=("Inter", 12),
                text_color=COLORS['text_secondary']
            ).pack(pady=5)
            
            customtkinter.CTkLabel(
                content_frame,
                text=item,
                font=("Inter", 13, "bold"),
                text_color=COLORS['accent_blue']
            ).pack(pady=5)
            
            customtkinter.CTkLabel(
                content_frame,
                text=f"Size: {size_str}",
                font=("Inter", 11),
                text_color=COLORS['text_muted']
            ).pack(pady=(0, 20))
            
            btn_frame = customtkinter.CTkFrame(content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", padx=20, pady=(0, 20))
            btn_frame.grid_columnconfigure((0, 1), weight=1)
            
            customtkinter.CTkButton(
                btn_frame, text="Reject",
                command=reject,
                font=("Inter", 13),
                fg_color="transparent",
                hover_color=COLORS['hover'],
                border_width=1, border_color=COLORS['border'],
                corner_radius=8, height=40
            ).grid(row=0, column=0, padx=5, sticky="ew")
            
            customtkinter.CTkButton(
                btn_frame, text="Accept",
                command=accept,
                font=("Inter", 13, "bold"),
                fg_color=COLORS['accent_green'],
                hover_color=self.adjust_color(COLORS['accent_green'], -20),
                corner_radius=8, height=40
            ).grid(row=0, column=1, padx=5, sticky="ew")
            
            dialog.wait_window()
            
        except Exception as e:
            self.add_log(f"Error in transfer prompt: {e}")
            result_container['accepted'] = False
            confirmation_event.set()

    def update_peer_list(self):
        if self.backend:
            peer_dict = self.backend.get_peer_dict()
            if set(self.peer_vars.keys()) != set(peer_dict.keys()):
                self.force_update_peer_list()
        self.after(3000, self.update_peer_list)
        
    def force_update_peer_list(self):
        for widget in self.peers_list_frame.winfo_children():
            widget.destroy()
        
        peer_dict = self.backend.get_peer_dict() if self.backend else {}
        self.peer_vars = {}
        
        self.peer_count_label.configure(text=str(len(peer_dict)))
        
        for peer in sorted(peer_dict.keys()):
            self.peer_vars[peer] = customtkinter.StringVar(value="off")
            
            peer_frame = customtkinter.CTkFrame(
                self.peers_list_frame,
                fg_color=COLORS['bg_secondary'],
                corner_radius=8,
                border_width=1,
                border_color=COLORS['border']
            )
            peer_frame.pack(fill="x", pady=5, padx=5)
            
            checkbox = customtkinter.CTkCheckBox(
                peer_frame,
                text=peer,
                variable=self.peer_vars[peer],
                onvalue=peer,
                offvalue="off",
                font=("Inter", 12),
                text_color=COLORS['text_primary'],
                fg_color=COLORS['accent_blue'],
                hover_color=self.adjust_color(COLORS['accent_blue'], -20),
                border_color=COLORS['border']
            )
            checkbox.pack(padx=15, pady=12, anchor="w")

    def update_sharable_files_list(self):
        for widget in self.files_list_frame.winfo_children():
            if widget != self.drop_hint:
                widget.destroy()
        
        self.file_vars = {}
        
        try:
            items = []
            for item_name in sorted(os.listdir(SHARE_DIR), key=str.lower):
                display_text = item_name
                is_folder = os.path.isdir(os.path.join(SHARE_DIR, item_name))
                if is_folder:
                    display_text += FOLDER_TAG
                items.append((display_text, is_folder))
            
            self.file_count_label.configure(text=f"{len(items)} item{'s' if len(items) != 1 else ''}")
            
            if items:
                self.drop_hint.pack_forget()
                
                for display_text, is_folder in items:
                    self.file_vars[display_text] = customtkinter.StringVar(value="off")
                    
                    file_frame = customtkinter.CTkFrame(
                        self.files_list_frame,
                        fg_color=COLORS['bg_secondary'],
                        corner_radius=8,
                        border_width=1,
                        border_color=COLORS['border']
                    )
                    file_frame.pack(fill="x", pady=5, padx=5)
                    
                    checkbox = customtkinter.CTkCheckBox(
                        file_frame,
                        text=display_text,
                        variable=self.file_vars[display_text],
                        onvalue=display_text,
                        offvalue="off",
                        font=("Inter", 11),
                        text_color=COLORS['text_primary'],
                        fg_color=COLORS['accent_purple'] if is_folder else COLORS['accent_blue'],
                        hover_color=self.adjust_color(COLORS['accent_purple'] if is_folder else COLORS['accent_blue'], -20),
                        border_color=COLORS['border']
                    )
                    checkbox.pack(padx=15, pady=10, anchor="w")
            else:
                self.drop_hint.pack(fill="both", expand=True, padx=20, pady=40)
                
        except FileNotFoundError:
            self.add_log(f"Error: Share directory not found.")
            self.file_count_label.configure(text="0 items")
    
    def get_selected_peers(self):
        return [peer for peer, var in self.peer_vars.items() if var.get() != "off"]
    
    def get_selected_files(self):
        return [item for item, var in self.file_vars.items() if var.get() != "off"]
    
    def handle_drop(self, event):
        filepaths = self.tk.splitlist(event.data)
        for path in filepaths:
            self.add_item_to_share(path)
        self.update_sharable_files_list()
        
    def add_item_to_share(self, path):
        if not os.path.exists(path):
            self.add_log(f"Path does not exist: {path}")
            return
        item_name = os.path.basename(path)
        destination = os.path.join(SHARE_DIR, item_name)
        try:
            if os.path.isdir(path):
                if os.path.exists(destination):
                    self.add_log(f"Folder '{item_name}' already exists in share directory.")
                    return
                shutil.copytree(path, destination)
                self.add_log(f"Added folder '{item_name}' to share directory.")
            else:
                if os.path.exists(destination):
                    self.add_log(f"File '{item_name}' already exists in share directory.")
                    return
                shutil.copy(path, destination)
                self.add_log(f"Added file '{item_name}' to share directory.")
        except Exception as e:
            self.add_log(f"Error adding '{item_name}': {e}")
        
    def add_files_dialog(self):
        filepaths = customtkinter.filedialog.askopenfilenames()
        if not filepaths:
            return
        for path in filepaths:
            self.add_item_to_share(path)
        self.update_sharable_files_list()

    def add_folder_dialog(self):
        folderpath = customtkinter.filedialog.askdirectory()
        if not folderpath:
            return
        self.add_item_to_share(folderpath)
        self.update_sharable_files_list()

    def delete_selected_items(self):
        selected_items = self.get_selected_files()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select items to delete.")
            return
        if messagebox.askyesno("Confirm Deletion", f"Delete {len(selected_items)} item(s)?"):
            for item_display_name in selected_items:
                item_name = item_display_name.replace(FOLDER_TAG, "")
                item_path = os.path.join(SHARE_DIR, item_name)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        self.add_log(f"Deleted folder '{item_name}'.")
                    else:
                        os.remove(item_path)
                        self.add_log(f"Deleted file '{item_name}'.")
                except OSError as e:
                    self.add_log(f"Error deleting '{item_name}': {e}")
            self.update_sharable_files_list()
    
    def send_selected_items(self):
        selected_peers = self.get_selected_peers()
        if not selected_peers:
            messagebox.showinfo("No Peer Selected", "Please select at least one peer to send to.")
            return
        selected_items = self.get_selected_files()
        if not selected_items:
            messagebox.showinfo("No Items Selected", "Please select at least one item to send.")
            return
        
        for peer in selected_peers:
            for item_display in selected_items:
                item_name = item_display.replace(FOLDER_TAG, "")
                threading.Thread(target=self.backend.send_item, args=(peer, item_name), daemon=True).start()

if __name__ == '__main__':
    app = App()
    app.setup_ui()
    app.setup_backend()
    app.mainloop()