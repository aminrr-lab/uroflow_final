import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, ttk
import sys
import os
import threading
import time
import queue
from PIL import Image
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import sqlite3
from tkcalendar import DateEntry
import datetime
from fpdf import FPDF
import csv
import subprocess
import re
import win32api

def resource_path(relative_path):
    import sys, os
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))  # <- GANTI INI
    return os.path.join(base_path, relative_path)

try:
    import serial
except ImportError:
    serial = None

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

COM_PORT = "COM19"
BAUDRATE = 115200

sidebar_bg_color = "#D4EBF8"
BTN_WIDTH = 160
BTN_HEIGHT = 44
BTN_FONT = ("Arial", 16, "bold")
BTN_ANCHOR = "w"
BTN_SPACING = 12

def setup_database():
    conn = sqlite3.connect('hospital_doctor.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS hospitals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT,
            first_name TEXT,
            last_name TEXT,
            gender TEXT,
            age INTEGER,
            date TEXT,
            time TEXT,
            hospital_name TEXT,
            doctor_name TEXT
        )
    ''')
    try:
        c.execute("ALTER TABLE patients ADD COLUMN hospital_name TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE patients ADD COLUMN doctor_name TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

class SerialReader(threading.Thread):
    def __init__(self, port, baudrate, data_queue, stop_event):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.data_queue = data_queue
        self.stop_event = stop_event
        self.ser = None

    def run(self):
        try:
            if serial is None:
                raise ImportError("pyserial not installed")
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            while not self.stop_event.is_set():
                line = self.ser.readline()
                if line:
                    try:
                        # Coba decode dengan utf-8, jika gagal, coba latin-1 atau ignore
                        decoded_line = line.decode('utf-8').strip()
                        if "Calibration prosess..." in decoded_line:
                            self.data_queue.put("Calibration prosess...")
                        elif "[NOT CALIBRATED]" in decoded_line:
                            self.data_queue.put("0.00,0.0 [NOT CALIBRATED]")
                        else:
                            parts = decoded_line.split(',')
                            if len(parts) >= 2:
                                try:
                                    flow = float(parts[0])
                                    volume = float(parts[1])
                                    status = parts[2].strip() if len(parts) > 2 else None
                                    self.data_queue.put((flow, volume, status))
                                except ValueError:
                                    pass

                            # parts = decoded_line.split(',')
                            # if len(parts) == 2:
                            #     flow, volume = float(parts[0]), float(parts[1])
                            #     self.data_queue.put((flow, volume))
                            elif len(parts) == 1 and parts[0].strip() == "CALIBRATED":
                                self.data_queue.put("CALIBRATED") # Menambahkan status CALIBRATED
                    except UnicodeDecodeError:
                        try:
                            decoded_line = line.decode('latin-1').strip()
                            if "Calibration prosess..." in decoded_line:
                                self.data_queue.put("Calibration prosess...")
                            elif "[NOT CALIBRATED]" in decoded_line:
                                self.data_queue.put("0.00,0.0 [NOT CALIBRATED]")
                            else:
                                parts = decoded_line.split(',')
                                if len(parts) == 2:
                                    flow, volume = float(parts[0]), float(parts[1])
                                    self.data_queue.put((flow, volume))
                                elif len(parts) == 1 and parts[0].strip() == "CALIBRATED":
                                    self.data_queue.put("CALIBRATED") # Menambahkan status CALIBRATED
                        except Exception:
                            continue # Abaikan baris yang tidak bisa di-decode atau di-parse
            self.ser.close()
        except (serial.SerialException, ImportError) as e:
            self.data_queue.put(('error', str(e)))

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("UROSON")
        self.overrideredirect(True)
        self.geometry("1024x600+0+0")
        self.sidebar_bg_color = sidebar_bg_color

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color=self.sidebar_bg_color)
        self.sidebar_frame.grid(row=0, column=0, sticky="nswe")
        for i in range(10):
            self.sidebar_frame.grid_rowconfigure(i, weight=0)
        self.sidebar_frame.grid_rowconfigure(7, weight=1)

        logo_image = Image.open(resource_path("logoEDISONHD.png"))
        self.logo_photo = ctk.CTkImage(light_image=logo_image, size=(160, 80))
        logo_label = ctk.CTkLabel(self.sidebar_frame, image=self.logo_photo, text="")
        logo_label.grid(row=0, column=0, pady=(20, BTN_SPACING + 3), padx=20, sticky="w")

        self.btn_start = ctk.CTkButton(
            self.sidebar_frame, text="▶️  Start", font=BTN_FONT, width=BTN_WIDTH, height=BTN_HEIGHT,
            anchor=BTN_ANCHOR, command=self.start_serial
        )
        self.btn_start.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, BTN_SPACING))
        self.btn_stop = ctk.CTkButton(
            self.sidebar_frame, text="⏹️  Stop", font=BTN_FONT, width=BTN_WIDTH, height=BTN_HEIGHT,
            anchor=BTN_ANCHOR, command=self.stop_serial
        )
        self.btn_stop.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, BTN_SPACING))
        self.btn_clear = ctk.CTkButton(
            self.sidebar_frame, text="🧹  Clear", font=BTN_FONT, width=BTN_WIDTH, height=BTN_HEIGHT,
            anchor=BTN_ANCHOR, command=self.clear_plot
        )
        self.btn_clear.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, BTN_SPACING))
        self.btn_setting = ctk.CTkButton(
            self.sidebar_frame, text="⚙️  Setting", font=BTN_FONT, width=BTN_WIDTH, height=BTN_HEIGHT,
            anchor=BTN_ANCHOR, command=self.show_setting
        )
        self.btn_setting.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, BTN_SPACING))

        self.btn_calibration = ctk.CTkButton(
            self.sidebar_frame, text="🔧  Calibration", font=BTN_FONT, width=BTN_WIDTH, height=BTN_HEIGHT,
            anchor=BTN_ANCHOR, command=self.show_calibration
        )
        self.btn_calibration.grid(row=5, column=0, sticky="ew", padx=20, pady=(0, BTN_SPACING))

        self.btn_restart = ctk.CTkButton(
            self.sidebar_frame, text="🔄  Restart", font=BTN_FONT, width=BTN_WIDTH, height=BTN_HEIGHT,
            anchor=BTN_ANCHOR, command=self.restart
        )
        self.btn_restart.grid(row=8, column=0, sticky="ew", padx=20, pady=(0, BTN_SPACING))
        self.btn_shutdown = ctk.CTkButton(
            self.sidebar_frame, text="⏻  Shutdown", font=BTN_FONT, width=BTN_WIDTH, height=BTN_HEIGHT,
            anchor=BTN_ANCHOR, command=lambda: self.on_close(shutdown_windows=True)
        )
        self.btn_shutdown.grid(row=9, column=0, sticky="ew", padx=20, pady=(0, 18))

        self.container = ctk.CTkFrame(self)
        self.container.grid(row=0, column=1, sticky="nswe")
        self.grid_columnconfigure(1, weight=1)

        setup_database()

        self.frames = {}
        for F in (StartPage, SettingPage, CalibrationPage):
            frame = F(self.container, self)
            self.frames[F] = frame
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.current_page = StartPage
        self.show_start()
        self.serial_thread = None
        self.serial_stop_event = threading.Event()
        self.data_queue = queue.Queue()



    def show_start(self):
        self.frames[StartPage].tkraise()
        self.current_page = StartPage

    def show_setting(self):
        self.frames[SettingPage].refresh_hospital()
        self.frames[SettingPage].refresh_doctor()
        self.frames[SettingPage].tkraise()
        self.current_page = SettingPage

    def show_calibration(self):
        self.frames[CalibrationPage].refresh_data_calibration()
        self.frames[CalibrationPage].tkraise()
        self.current_page = CalibrationPage

    def start_serial(self):
        if self.current_page == SettingPage or self.current_page == CalibrationPage:
            self.show_start()
            return
        self.stop_serial()
        self.frames[StartPage].clear_plot()
        self.serial_stop_event.clear()
        self.serial_thread = SerialReader(COM_PORT, BAUDRATE, self.data_queue, self.serial_stop_event)
        self.serial_thread.start()
        self.after(100, self.update_plot)

    def stop_serial(self):
        if self.serial_thread:
            self.serial_stop_event.set()
            self.serial_thread = None

    def clear_plot(self):
        self.frames[StartPage].clear_plot()

    def update_plot(self):
        frame = self.frames[StartPage]
        while not self.data_queue.empty():
            val = self.data_queue.get()
            if isinstance(val, tuple) and len(val) >= 2 and val[0] != 'error':
                flow = val[0]
                volume = val[1]
                status = val[2] if len(val) > 2 else None
                frame.add_data(flow, volume, status)
            elif val and val[0] == 'error':
                messagebox.showerror("Serial Error", f"Failed to open serial port: {val[1]}")
                self.stop_serial()
        if self.serial_thread and not self.serial_stop_event.is_set():
            self.after(100, self.update_plot)

    def restart(self, windows_restart=False):
        self.stop_serial()
        if windows_restart:
            if messagebox.askyesno("Restart Windows", "Yakin ingin restart Windows?"):
                os.system("shutdown /r /t 0")
        else:
            python = sys.executable
            os.execl(python, python, *sys.argv)

    def on_close(self, shutdown_windows=False):
        self.stop_serial()
        self.destroy()
        if shutdown_windows:
            os.system("shutdown /s /t 0")
        else:
            self.destroy()

    def send_serial_data(self, data_bytes: bytes):
        # Helper method to send bytes to serial device if connected
        if self.serial_thread and self.serial_thread.ser and self.serial_thread.ser.is_open:
            try:
                self.serial_thread.ser.write(data_bytes)
            except Exception as e:
                messagebox.showerror("Serial Error", f"Failed to send data to device: {e}")
        else:
            messagebox.showwarning("Serial Warning", "Serial port not connected or open.")

class StartPage(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        self.flow_data = []
        self.volume_data = []

        self.fig = Figure(figsize=(7,4), dpi=100)
        self.ax1 = self.fig.add_subplot(211)
        self.ax2 = self.fig.add_subplot(212)
        self.ax1.set_xlim(0,90)
        self.ax2.set_xlim(0,90)
        self.ax1.set_ylim(0,100)
        self.ax2.set_ylim(0,300)
        self.ax2.set_xlabel("Waktu (s)")
        self.ax1.set_ylabel("Flowmeter")
        self.ax2.set_ylabel("Volume")
        self.ax1.grid(True, linestyle='--', alpha=0.7)
        self.ax2.grid(True, linestyle='--', alpha=0.7)
        self.line1, = self.ax1.plot([], [], 'r-')
        self.line2, = self.ax2.plot([], [], 'b-')
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=20, pady=10)
        self.xdata = []
        self.ydata1 = []
        self.ydata2 = []
        self.start_time = None

        info = ctk.CTkFrame(self)
        info.pack(fill="x", padx=18, pady=8)
        self.lbl_flow = ctk.CTkLabel(info, text="Flowmeter: 0", font=("Arial", 20))
        self.lbl_flow.pack(side="left", padx=10)
        self.lbl_vol = ctk.CTkLabel(info, text="Volume: 0", font=("Arial", 20))
        self.lbl_vol.pack(side="left", padx=10)
        self.lbl_status = ctk.CTkLabel(info, text="Status: -", font=("Arial", 20))
        self.lbl_status.pack(side="left", padx=10)
        ctk.CTkButton(info, text="💾 Save", font=("Arial", 14, "bold"), width=110, height=34, anchor="w", command=self.save_data).pack(side="right", padx=10)
        ctk.CTkButton(info, text="📄 Report", font=("Arial", 14, "bold"), width=110, height=34, anchor="w", command=self.report).pack(side="right", padx=10)

    def add_data(self, flow, volume, status=None):
        t = time.time()
        if not self.start_time:
            self.start_time = t
        elapsed = t - self.start_time
        self.xdata.append(elapsed)
        self.ydata1.append(flow)
        self.ydata2.append(volume)

        self.flow_data.append(flow)
        self.volume_data.append(volume)

        while self.xdata and self.xdata[0] < elapsed-90:
            self.xdata.pop(0)
            self.ydata1.pop(0)
            self.ydata2.pop(0)
            self.flow_data.pop(0)
            self.volume_data.pop(0)
        self.line1.set_data(self.xdata, self.ydata1)
        self.line2.set_data(self.xdata, self.ydata2)
        self.ax1.set_xlim(max(0, elapsed-90), max(90, elapsed))
        self.ax2.set_xlim(max(0, elapsed-90), max(90, elapsed))
        self.canvas.draw_idle()
        self.lbl_flow.configure(text=f"Flowmeter: {flow}")
        self.lbl_vol.configure(text=f"Volume: {volume}")
        if status:
            color = "#28a745" if status.upper() == "CALIBRATED" else (
                "#d9534f" if "NOT CALIBRATED" in status.upper() else "#333333")
            self.lbl_status.configure(text=f"Status: {status}", text_color=color)
            # self.lbl_status.configure(text=f"Status: {status}")


    def clear_plot(self):
        self.xdata.clear()
        self.ydata1.clear()
        self.ydata2.clear()
        self.flow_data.clear()
        self.volume_data.clear()
        self.lbl_status.configure(text="Status: -", text_color="#333333")
        self.start_time = None
        self.line1.set_data([], [])
        self.line2.set_data([], [])
        self.ax1.set_xlim(0,90)
        self.ax2.set_xlim(0,90)
        self.canvas.draw_idle()
        self.lbl_flow.configure(text="Flowmeter: 0")
        self.lbl_vol.configure(text="Volume: 0")

    def save_data(self):
        win = tk.Toplevel(self)
        win.title("Patient Information")
        win.geometry("450x480")
        win.grab_set()

        frame = tk.Frame(win)
        frame.pack(padx=20, pady=20, fill="both", expand=True)

        tk.Label(frame, text="ID Patient:").grid(row=0, column=0, sticky="w")
        entry_id = tk.Entry(frame)
        entry_id.grid(row=0, column=1, sticky="ew")

        tk.Label(frame, text="First Name:").grid(row=1, column=0, sticky="w")
        entry_first = tk.Entry(frame)
        entry_first.grid(row=1, column=1, sticky="ew")

        tk.Label(frame, text="Last Name:").grid(row=2, column=0, sticky="w")
        entry_last = tk.Entry(frame)
        entry_last.grid(row=2, column=1, sticky="ew")

        tk.Label(frame, text="Gender:").grid(row=3, column=0, sticky="w")
        gender_var = tk.StringVar(value="Male")
        gender_menu = ttk.Combobox(frame, textvariable=gender_var, values=["Male", "Female"], state="readonly")
        gender_menu.grid(row=3, column=1, sticky="ew")

        tk.Label(frame, text="Age:").grid(row=4, column=0, sticky="w")
        entry_age = tk.Entry(frame)
        entry_age.grid(row=4, column=1, sticky="ew")

        tk.Label(frame, text="Hospital:").grid(row=5, column=0, sticky="w")
        hospital_var = tk.StringVar()
        hospital_menu = ttk.Combobox(frame, textvariable=hospital_var, state="readonly")
        hospital_menu.grid(row=5, column=1, sticky="ew")

        tk.Label(frame, text="Doctor:").grid(row=6, column=0, sticky="w")
        doctor_var = tk.StringVar()
        doctor_menu = ttk.Combobox(frame, textvariable=doctor_var, state="readonly")
        doctor_menu.grid(row=6, column=1, sticky="ew")

        tk.Label(frame, text="Date:").grid(row=7, column=0, sticky="w")
        date_var = tk.StringVar()
        date_entry = DateEntry(frame, textvariable=date_var, date_pattern="yyyy-mm-dd")
        date_entry.set_date(datetime.date.today())
        date_entry.grid(row=7, column=1, sticky="ew")

        tk.Label(frame, text="Time:").grid(row=8, column=0, sticky="w")
        time_var = tk.StringVar()
        now = datetime.datetime.now().strftime("%H:%M:%S")
        time_var.set(now)
        entry_time = tk.Entry(frame, textvariable=time_var, state="readonly")
        entry_time.grid(row=8, column=1, sticky="ew")

        conn = sqlite3.connect('hospital_doctor.db')
        c = conn.cursor()
        c.execute("SELECT name FROM hospitals ORDER BY id")
        hospitals = [row[0] for row in c.fetchall()]
        c.execute("SELECT name FROM doctors ORDER BY id")
        doctors = [row[0] for row in c.fetchall()]
        conn.close()

        hospital_menu['values'] = hospitals
        doctor_menu['values'] = doctors
        if hospitals:
            hospital_var.set(hospitals[0])
        else:
            hospital_var.set('')

        if doctors:
            doctor_var.set(doctors[0])
        else:
            doctor_var.set('')

        def submit():
            pid = entry_id.get().strip()
            first = entry_first.get().strip()
            last = entry_last.get().strip()
            gender = gender_var.get()
            age = entry_age.get().strip()
            hospital = hospital_var.get()
            doctor = doctor_var.get()
            date = date_var.get()
            time_ = time_var.get()

            if not (pid and first and last and age and hospital and doctor):
                messagebox.showerror("Error", "All fields including hospital and doctor must be filled!")
                return
            try:
                age_int = int(age)
            except:
                messagebox.showerror("Error", "Age must be a number!")
                return

            # --- BAGIAN PERUBAHAN UNTUK CSV ---
            # Tentukan direktori output
            output_directory = r"C:\Users\uroson\Documents"  # Gunakan raw string untuk path Windows
            # Buat direktori jika belum ada
            try:
                os.makedirs(output_directory, exist_ok=True)
            except OSError as e:
                messagebox.showerror("Error", f"Failed to create directory {output_directory}: {e}")
                return
            # Gabungkan direktori dengan nama file
            filename = f"{pid}_{first}_{last}_data.csv"
            file_path = os.path.join(output_directory, filename)

            conn = sqlite3.connect('hospital_doctor.db')
            c = conn.cursor()
            c.execute("INSERT INTO patients (patient_id, first_name, last_name, gender, age, date, time, hospital_name, doctor_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (pid, first, last, gender, age_int, date, time_, hospital, doctor))
            conn.commit()
            conn.close()

            # Save flow and volume data to CSV with patient_id, first and last name for unique filename
            filename = f"{pid}_{first}_{last}_data.csv"
            with open(file_path, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Time (s)", "Flow", "Volume"])
                for i in range(len(self.xdata)):
                    writer.writerow([self.xdata[i], self.ydata1[i], self.ydata2[i]])

            messagebox.showinfo("Success", "Patient data saved!")
            win.destroy()

        btn_submit = tk.Button(frame, text="Submit", command=submit, bg="#0078D7", fg="white", font=("Arial", 12, "bold"))
        btn_submit.grid(row=9, column=0, columnspan=2, pady=20, sticky="ew")

        for i in range(10):
            frame.grid_rowconfigure(i, pad=8)
        frame.grid_columnconfigure(1, weight=1)

    def load_patient_data(self, patient_id):
        self.xdata.clear()
        self.ydata1.clear()
        self.ydata2.clear()
        self.flow_data.clear()
        self.volume_data.clear()
        self.start_time = None
        output_directory = r"C:\Users\uroson\Documents"  # Tambahkan ini

        try:
            filename = None
            # Find matching CSV file based on patient_id, first name, last name if needed
            # Here we try to find any CSV file starting with patient_id_
            # This assumes files are saved as "{pid}_{first}_{last}_data.csv"
            # files = [f for f in os.listdir('.') if f.endswith('_data.csv') and f.startswith(f"{patient_id}_")]
            files = [os.path.join(output_directory, f) for f in os.listdir(output_directory) if
                    f.endswith('_data.csv') and f.startswith(f"{patient_id}_")]
            if files:
                filename = files[0]
            else:
                fallback_path = os.path.join(output_directory, f"{patient_id}_data.csv")
                if os.path.exists(fallback_path):
                    filename = fallback_path  # Pastikan filename sekarang adalah path lengkap
                # fallback: try {patient_id}_data.csv
                # fallback = f"{patient_id}_data.csv"
                # if os.path.exists(fallback):
                #     filename = fallback

            if filename is None:
                raise FileNotFoundError()

            with open(filename, mode='r') as file:
                reader = csv.reader(file)
                next(reader)
                for row in reader:
                    time_val, flow, volume = map(float, row)
                    self.xdata.append(time_val)
                    self.ydata1.append(flow)
                    self.ydata2.append(volume)
                    self.flow_data.append(flow)
                    self.volume_data.append(volume)
            if self.xdata:
                self.start_time = time.time() - self.xdata[-1]

            self.line1.set_data(self.xdata, self.ydata1)
            self.line2.set_data(self.xdata, self.ydata2)
            if self.xdata:
                min_x = max(0, self.xdata[-1] - 90)
                max_x = max(90, self.xdata[-1])
            else:
                min_x, max_x = 0, 90
            self.ax1.set_xlim(min_x, max_x)
            self.ax2.set_xlim(min_x, max_x)
            self.canvas.draw_idle()

            if self.ydata1:
                self.lbl_flow.configure(text=f"Flowmeter: {self.ydata1[-1]:.2f}")
            else:
                self.lbl_flow.configure(text="Flowmeter: 0")
            if self.ydata2:
                self.lbl_vol.configure(text=f"Volume: {self.ydata2[-1]:.2f}")
            else:
                self.lbl_vol.configure(text="Volume: 0")

        except FileNotFoundError:
            print(f"No data file found for patient {patient_id}.")
            self.clear_plot()

    def report(self):
        win = tk.Toplevel(self)
        win.title("Patient Report")
        win.geometry("700x400")
        win.grab_set()

        frame_hist = tk.Frame(win)
        frame_hist.pack(fill="both", expand=True, padx=10, pady=10)

        columns = ("No", "Patient Name", "Date", "Time")
        tree = ttk.Treeview(frame_hist, columns=columns, show="headings", height=10)
        for col in columns:
            tree.heading(col, text=col)
        tree.column("No", width=40, anchor="center")
        tree.column("Patient Name", width=200, anchor="center")
        tree.column("Date", width=100, anchor="center")
        tree.column("Time", width=100, anchor="center")
        tree.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(frame_hist, orient="vertical", command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.config(yscrollcommand=sb.set)

        # Tentukan direktori output untuk PDF
        output_pdf_directory = r"C:\Users\uroson\Documents"  # Gunakan raw string
        # Buat direktori jika belum ada (bisa juga dilakukan sekali di __init__ App)
        try:
            os.makedirs(output_pdf_directory, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Error", f"Failed to create directory {output_pdf_directory}: {e}")
            return  # Hentikan jika direktori tidak bisa dibua

        def load_data():
            for item in tree.get_children():
                tree.delete(item)
            conn = sqlite3.connect('hospital_doctor.db')
            c = conn.cursor()
            c.execute("SELECT id, patient_id, first_name, last_name, date, time FROM patients ORDER BY id DESC")
            rows = c.fetchall()

            total = len(rows)
            for idx, (db_id, patient_id, first, last, date, time_) in enumerate(rows):
                display_num = total - idx  # Inverted numbering: 1 at bottom, highest at top
                tree.insert("", "end", iid=db_id, values=(display_num, f"{first} {last}", date, time_))

            # conn.close()
            # for idx, (db_id, patient_id, first, last, date, time_) in enumerate(rows, start=1):
            #     tree.insert("", "end", iid=db_id, values=(idx, f"{first} {last}", date, time_))

            self.clear_plot()

        load_data()

        def on_patient_select(event):
            selected = tree.selection()
            if selected:
                db_id = selected[0]
                conn = sqlite3.connect('hospital_doctor.db')
                c = conn.cursor()
                c.execute("SELECT patient_id, first_name, last_name FROM patients WHERE id=?", (db_id,))
                result = c.fetchone()
                conn.close()
                if result:
                    patient_id_str, first_name, last_name = result
                    # Load plot data from CSV file named as patient_id_first_last_data.csv
                    filename = f"{patient_id_str}_{first_name}_{last_name}_data.csv"
                    if os.path.exists(os.path.join(output_pdf_directory, filename)): # Perbaikan path
                        try:
                            self.load_specific_csv(os.path.join(output_pdf_directory, filename)) # Perbaikan path
                        except Exception as e:
                            print("Error loading CSV file:", e)
                            self.clear_plot()
                    else:
                        # fallback to load patient_id only CSV
                        self.load_patient_data(patient_id_str)
                else:
                    self.clear_plot()
            else:
                self.clear_plot()

        tree.bind("<<TreeviewSelect>>", on_patient_select)

        frame_btn = tk.Frame(win)
        frame_btn.pack(fill="x", padx=10, pady=(0, 10))


        def generate_pdf_and_open():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Warning", "Select a patient first!")
                return
            pid = sel[0]
            conn = sqlite3.connect('hospital_doctor.db')
            c = conn.cursor()
            c.execute("SELECT first_name, last_name, patient_id FROM patients WHERE id=?", (pid,))
            patient = c.fetchone()
            conn.close()
            if patient:
                first_name, last_name, patient_id_str = patient
                pdf_filename = f"{first_name}_{last_name}_report.pdf"
                # --- BAGIAN PERUBAHAN UNTUK PDF (View) ---
                # pdf_filename = f"{first_name}_{last_name}_report.pdf"
                pdf_file_path = os.path.join(output_pdf_directory, pdf_filename)
                try:
                    self.generate_pdf(patient_id_str, first_name, last_name, pdf_file_path)
                    sumatra_path = r"C:\Users\uroson\AppData\Local\SumatraPDF\SumatraPDF.exe"
                    if sys.platform == "win32":
                        # Gunakan subprocess agar bisa tentukan exe secara spesifik
                        # subprocess.Popen([acrobat_path, "/t", os.path.abspath(pdf_filename)])
                        # subprocess.Popen([sumatra_path, pdf_filename])
                        subprocess.Popen([r"C:\Users\uroson\AppData\Local\SumatraPDF\SumatraPDF.exe", pdf_file_path])
                    elif sys.platform == "darwin":
                        os.system(f"open '{pdf_filename}'")
                    else:
                        os.system(f"xdg-open '{pdf_filename}'")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to generate or open PDF: {e}")


        def print_pdf():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Warning", "Select a patient first!")
                return

            pid = sel[0]
            conn = sqlite3.connect('hospital_doctor.db')
            c = conn.cursor()
            c.execute("SELECT first_name, last_name, patient_id FROM patients WHERE id=?", (pid,))
            patient = c.fetchone()
            conn.close()

            if patient:
                first_name, last_name, patient_id_str = patient
                pdf_filename = f"{first_name}_{last_name}_report.pdf"
                # Pastikan output_pdf_directory sudah didefinisikan di scope yang benar (misal di __init__ atau di luar fungsi)
                # Jika output_pdf_directory didefinisikan di dalam generate_pdf_and_open, maka perlu diakses atau didefinisikan ulang di sini.
                # Asumsi output_pdf_directory sudah tersedia di scope ini.
                output_pdf_directory = r"C:\Users\uroson\Documents" # Pastikan ini konsisten dengan generate_pdf_and_open
                pdf_file_path = os.path.join(output_pdf_directory, pdf_filename)

                # ✅ Tambahkan validasi sebelum cetak
                if not os.path.exists(pdf_file_path):
                    try:
                        self.generate_pdf(patient_id_str, first_name, last_name, pdf_file_path)
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to generate PDF: {e}")
                        return

                # ✅ Tambahan pengecekan lagi sebelum print
                if not os.path.exists(pdf_file_path):
                    messagebox.showerror("Error", f"File PDF tidak ditemukan: {pdf_file_path}")
                    return

                # Generate PDF if it doesn't exist
                if not os.path.exists(pdf_file_path): # <-- Perbaikan di sini
                    try:
                        self.generate_pdf(patient_id_str, first_name, last_name, pdf_file_path) # <-- Perbaikan di sini, kirim full path
                    except Exception as e:
                        messagebox.showerror("Error", f"Failed to generate PDF: {e}")
                        return

                try:
                    # Send PDF to default printer using ShellExecute
                    win32api.ShellExecute(
                        0,
                        "print",
                        pdf_file_path, # <-- Perbaikan di sini
                        None,
                        ".",
                        0
                    )
                    messagebox.showinfo("Print PDF", "PDF sent to default printer.")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to print PDF: {e}")

        def delete_patient():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Warning", "Select a patient first!")
                return
            pid = sel[0]
            if messagebox.askyesno("Delete", "Are you sure to delete this patient?"):
                conn = sqlite3.connect('hospital_doctor.db')
                c = conn.cursor()
                c.execute("DELETE FROM patients WHERE id=?", (pid,))
                conn.commit()
                conn.close()
                load_data()
                self.clear_plot()

        def refresh():
            load_data()
            self.clear_plot()

        btn_view = tk.Button(frame_btn, text="View PDF", command=generate_pdf_and_open, width=12, bg="#0078D7",
                             fg="white", font=("Arial", 11, "bold"))
        btn_view.pack(side="left", padx=5)
        btn_print = tk.Button(frame_btn, text="Print PDF", command=print_pdf, width=12, bg="#0078D7", fg="white",
                              font=("Arial", 11, "bold"))
        btn_print.pack(side="left", padx=5)
        btn_delete = tk.Button(frame_btn, text="Delete", command=delete_patient, width=12, bg="#D70022", fg="white",
                               font=("Arial", 11, "bold"))
        btn_delete.pack(side="left", padx=5)
        btn_refresh = tk.Button(frame_btn, text="Refresh", command=refresh, width=12, bg="#0078D7", fg="white",
                                font=("Arial", 11, "bold"))
        btn_refresh.pack(side="left", padx=5)

    def load_specific_csv(self, filename):
        self.xdata.clear()
        self.ydata1.clear()
        self.ydata2.clear()
        self.flow_data.clear()
        self.volume_data.clear()
        self.start_time = None

        with open(filename, mode='r') as file:
            reader = csv.reader(file)
            next(reader)
            for row in reader:
                time_val, flow, volume = map(float, row)
                self.xdata.append(time_val)
                self.ydata1.append(flow)
                self.ydata2.append(volume)
                self.flow_data.append(flow)
                self.volume_data.append(volume)
        if self.xdata:
            self.start_time = time.time() - self.xdata[-1]

        self.line1.set_data(self.xdata, self.ydata1)
        self.line2.set_data(self.xdata, self.ydata2)
        if self.xdata:
            min_x = max(0, self.xdata[-1] - 90)
            max_x = max(90, self.xdata[-1])
        else:
            min_x, max_x = 0, 90
        self.ax1.set_xlim(min_x, max_x)
        self.ax2.set_xlim(min_x, max_x)
        self.canvas.draw_idle()

        if self.ydata1:
            self.lbl_flow.configure(text=f"Flowmeter: {self.ydata1[-1]:.2f}")
        else:
            self.lbl_flow.configure(text="Flowmeter: 0")
        if self.ydata2:
            self.lbl_vol.configure(text=f"Volume: {self.ydata2[-1]:.2f}")
        else:
            self.lbl_vol.configure(text="Volume: 0")

    def generate_pdf(self, patient_id, first_name, last_name, pdf_file_path):
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=10)
        pdf.add_page()

        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 8, 'Patient Report', ln=1, align='C')

        conn = sqlite3.connect('hospital_doctor.db')
        c = conn.cursor()
        c.execute(
            "SELECT first_name, last_name, patient_id, gender, age, date, time, hospital_name, doctor_name FROM patients WHERE id=(SELECT id FROM patients WHERE patient_id=? LIMIT 1)",
            (patient_id,))
        patient = c.fetchone()

        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 6, 'Hospital Information', ln=1)
        pdf.set_font("Arial", '', 10)
        if patient and patient[7]:
            c.execute("SELECT address FROM hospitals WHERE name=?", (patient[7],))
            hosp_addr = c.fetchone()
            if hosp_addr:
                pdf.cell(0, 5, f"Name: {patient[7]}, Address: {hosp_addr[0]}", ln=1)
            else:
                pdf.cell(0, 5, f"Name: {patient[7]}", ln=1)
        pdf.ln(2)

        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 6, 'Patient Information', ln=1)
        pdf.set_font("Arial", '', 10)
        if patient:
            pdf.cell(0, 5,
                     f"ID: {patient[2]}, Name: {patient[0]} {patient[1]}, Gender: {patient[3]}, Age: {patient[4]}, Date: {patient[5]}, Time: {patient[6]}",
                     ln=1)
        pdf.ln(2)

        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 6, 'Doctor Information', ln=1)
        pdf.set_font("Arial", '', 10)
        if patient and patient[8]:
            pdf.cell(0, 5, f"Doctor: {patient[8]}", ln=1)
        pdf.ln(2)

        # Clear previous data
        self.xdata.clear()
        self.ydata1.clear()
        self.ydata2.clear()
        self.flow_data.clear()
        self.volume_data.clear()
        self.start_time = None

        # Tentukan direktori tempat CSV disimpan
        csv_data_directory = r"C:\Users\uroson\Documents"  # Ini adalah lokasi yang baru Anda tentukan

        # Load data from CSV file by patient_id, first_name, last_name
        data_filename = f"{patient_id}_{first_name}_{last_name}_data.csv"
        # Gabungkan direktori dengan nama file CSV
        data_file_path = os.path.join(csv_data_directory, data_filename)
        if not os.path.exists(data_file_path):
            # fallback to older format
            data_filename = f"{patient_id}_data.csv"
            fallback_file_path = os.path.join(csv_data_directory, data_filename)  # Gabungkan juga dengan direktori baru
            if not os.path.exists(fallback_file_path): # Perbaikan: cek fallback_file_path
                # no data file, skip plot and stats
                max_flow = avg_flow = time_to_max_flow = last_volume = 0
                pdf.cell(0, 5, "No flow/volume data available.", ln=1)
                # Penting: return di sini jika tidak ada data untuk diproses lebih lanjut
                pdf.output(pdf_file_path)
                return
            else:
                data_file_path = fallback_file_path # Gunakan path fallback jika ada

        if os.path.exists(data_file_path):
            with open(data_file_path, mode='r') as file:
                reader = csv.reader(file)
                next(reader)
                for row in reader:
                    time_val, flow, volume = map(float, row)
                    self.xdata.append(time_val)
                    self.ydata1.append(flow)
                    self.ydata2.append(volume)
                    self.flow_data.append(flow)
                    self.volume_data.append(volume)

            if self.flow_data:
                max_flow = max(self.flow_data)
                max_index = self.flow_data.index(max_flow)

                time_to_max_flow = self.xdata[max_index] if max_index < len(self.xdata) else 0
                avg_flow = sum(self.flow_data) / len(self.flow_data)

                total_active_time = self.xdata[-1] - self.xdata[0] if len(self.xdata) > 1 else 0
                last_volume = self.volume_data[-1] if self.volume_data else 0
            else:
                max_flow = avg_flow = time_to_max_flow = total_active_time = last_volume = 0
            #
            # if self.flow_data:
            #     # Cari titik awal di mana flow > 6
            #     start_index = next((i for i, val in enumerate(self.flow_data) if val > 6), None)
            #
            #     if start_index is not None:
            #         # Cari akhir aliran aktif (flow turun <= 6 lagi)
            #         end_index = start_index
            #         for i in range(start_index, len(self.flow_data)):
            #             if self.flow_data[i] > 6:
            #                 end_index = i
            #             else:
            #                 break
            #
            #         active_flows = self.flow_data[start_index:end_index + 1]
            #         active_times = self.xdata[start_index:end_index + 1]
            #
            #     if active_flows:
            #         max_flow = max(active_flows)
            #         avg_flow = sum(active_flows) / len(active_flows)
            #         max_index = active_flows.index(max_flow)
            #         time_to_max_flow = active_times[max_index] - active_times[0]
            #         total_active_time = active_times[-1] - active_times[0]
            #         last_volume = self.volume_data[end_index] if end_index < len(self.volume_data) else 0
            #     else:
            #         max_flow = avg_flow = time_to_max_flow = total_active_time = last_volume = 0
            # else:
            #     max_flow = avg_flow = time_to_max_flow = total_active_time = last_volume = 0

            # Update figure with loaded data to have plot ready for saving image
            self.line1.set_data(self.xdata, self.ydata1)
            self.line2.set_data(self.xdata, self.ydata2)
            if self.xdata:
                min_x = max(0, self.xdata[-1] - 90)
                max_x = max(90, self.xdata[-1])
            else:
                min_x, max_x = 0, 90
            self.ax1.set_xlim(min_x, max_x)
            self.ax2.set_xlim(min_x, max_x)
            self.canvas.draw()

            pdf.set_font("Arial", 'B', 12)
            pdf.cell(0, 6, 'Flow and Volume Statistics', ln=1)
            pdf.set_font("Arial", '', 10)
            pdf.cell(0, 5, f"Maximum Flow Rate: {max_flow:.2f}", ln=1)
            pdf.cell(0, 5, f"Average Flow Rate: {avg_flow:.2f}", ln=1)
            pdf.cell(0, 5, f"Time to Maximum Flow Rate: {time_to_max_flow:.2f} seconds", ln=1)
            pdf.cell(0, 5, f"Total Recording Time: {total_active_time:.2f} seconds", ln=1)
            pdf.cell(0, 5, f"Last Volume Data: {last_volume:.2f}", ln=1)
            pdf.ln(2)

            flow_plot_path = "flowmeter_plot.png"
            self.fig.savefig(flow_plot_path, dpi=150)

            pdf.set_font("Arial", 'B', 12)
            pdf.cell(0, 6, 'Flowmeter and Volume Plots', ln=1)
            pdf.image(flow_plot_path, x=10, w=pdf.w - 20)

            if os.path.exists(flow_plot_path):
                try:
                    os.remove(flow_plot_path)
                except Exception:
                    pass

        pdf.output(pdf_file_path)

class CalibrationPage(ctk.CTkFrame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        self.configure(fg_color="#ffffff")  # white background

        # Main grid for 2x2 layout
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Frame 1: Live Data
        self.frame_live_data = ctk.CTkFrame(self, fg_color="#f9f9f9", corner_radius=12)
        self.frame_live_data.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
        self.create_live_data_frame(self.frame_live_data)

        # Frame 2: Panduan Live Data
        self.frame_panduan_live_data = ctk.CTkFrame(self, fg_color="#f9f9f9", corner_radius=12)
        self.frame_panduan_live_data.grid(row=0, column=1, padx=15, pady=15, sticky="nsew")
        self.create_panduan_live_data_frame(self.frame_panduan_live_data)

        # Frame 3: Calibration Settings
        self.frame_calibration_settings = ctk.CTkFrame(self, fg_color="#f9f9f9", corner_radius=12)
        self.frame_calibration_settings.grid(row=1, column=0, padx=15, pady=15, sticky="nsew")
        self.create_calibration_settings_frame(self.frame_calibration_settings)

        # Frame 4: Panduan Calibration Settings
        self.frame_panduan_calibration_settings = ctk.CTkFrame(self, fg_color="#f9f9f9", corner_radius=12)
        self.frame_panduan_calibration_settings.grid(row=1, column=1, padx=15, pady=15, sticky="nsew")
        self.create_panduan_calibration_settings_frame(self.frame_panduan_calibration_settings)

        # Data holders updated by the controller app on update or refresh
        self.current_flow = 0.0
        self.current_volume = 0.0
        self.current_tar = 0.0

        # Tambahkan variabel untuk thread dan queue
        self.calib_serial_thread = None
        self.calib_serial_stop_event = threading.Event()
        self.calib_data_queue = queue.Queue()

    def create_live_data_frame(self, parent_frame):
        lbl_title1 = ctk.CTkLabel(parent_frame, text="Live Data", font=ctk.CTkFont(size=20, weight="bold"), text_color="#222222")
        lbl_title1.pack(pady=(12,20))

        self.lbl_flow = ctk.CTkLabel(parent_frame, text="Flowmeter: 0.00", font=ctk.CTkFont(size=16, weight="normal"), text_color="#444444")
        self.lbl_flow.pack(pady=8, padx=12, anchor="w")
        self.lbl_volume = ctk.CTkLabel(parent_frame, text="Volume: 0.00", font=ctk.CTkFont(size=16, weight="normal"), text_color="#444444")
        self.lbl_volume.pack(pady=8, padx=12, anchor="w")

        # --- MODIFIKASI UNTUK BUTTON LIVE DATA ---
        button_frame_live = ctk.CTkFrame(parent_frame, fg_color="transparent")
        button_frame_live.pack(pady=(20, 12)) # Padding atas untuk frame tombol

        self.btn_zero_tar = ctk.CTkButton(
            button_frame_live, text="Zero", font=ctk.CTkFont(size=12, weight="bold"),
            width=80, height=30, command=self.zero_tar_clicked
        )
        self.btn_zero_tar.pack(side="left", padx=5) # Sejajarkan ke kiri dengan padding

        self.btn_start_cal = ctk.CTkButton(
            button_frame_live, text="Start", font=ctk.CTkFont(size=12, weight="bold"),
            width=80, height=30, command=self.start_serial_calibration
        )
        self.btn_start_cal.pack(side="left", padx=5) # Sejajarkan ke kiri dengan padding

        self.btn_stop_cal = ctk.CTkButton(
            button_frame_live, text="Stop", font=ctk.CTkFont(size=12, weight="bold"),
            width=80, height=30, command=self.stop_serial_calibration
        )
        self.btn_stop_cal.pack(side="left", padx=5) # Sejajarkan ke kiri dengan padding

        self.serial_running = False
        self.serial_stop_event = threading.Event()

    def create_panduan_live_data_frame(self, parent_frame):
        lbl_title = ctk.CTkLabel(parent_frame, text="Panduan Live Data", font=ctk.CTkFont(size=20, weight="bold"), text_color="#222222")
        lbl_title.pack(pady=(12,30))

        panduan_text = """
        Panduan untuk Live Data:
        1. Pastikan perangkat terhubung dengan benar.
        2. Klik 'Start' untuk memulai pembacaan data real-time.
        3. 'Flowmeter' menunjukkan laju aliran saat ini.
        4. 'Volume' menunjukkan total volume yang terakumulasi.
        5. Klik 'Stop' untuk menghentikan pembacaan data.
        6. 'Zero' digunakan untuk mereset beban.
        """
        ctk.CTkLabel(parent_frame, text=panduan_text, justify="left", wraplength=450, font=ctk.CTkFont(size=12)).pack(padx=10, pady=10, anchor="w")

    def create_calibration_settings_frame(self, parent_frame):
        lbl_title2 = ctk.CTkLabel(parent_frame, text="Calibration Settings", font=ctk.CTkFont(size=20, weight="bold"), text_color="#222222")
        lbl_title2.pack(pady=(12,20))

        setlow_frame = ctk.CTkFrame(parent_frame, fg_color="#f0f0f0", corner_radius=6)
        setlow_frame.pack(fill="x", pady=8, padx=12)
        lbl_setlow = ctk.CTkLabel(setlow_frame, text="Set Value Calibration:", font=ctk.CTkFont(size=14))
        lbl_setlow.pack(side="left", padx=12, pady=10)
        self.entry_setlow = ctk.CTkEntry(setlow_frame, placeholder_text="1000", width=120)
        self.entry_setlow.pack(side="left", padx=8, pady=10)

        # --- MODIFIKASI UNTUK BUTTON CALIBRATION SETTINGS ---
        button_frame_calib = ctk.CTkFrame(parent_frame, fg_color="transparent")
        button_frame_calib.pack(pady=(20, 12)) # Padding atas untuk frame tombol

        self.btn_send_values = ctk.CTkButton(
            button_frame_calib, text="Send", font=ctk.CTkFont(size=12, weight="bold"),
            width=80, height=30, command=self.send_calibration_values
        )
        self.btn_send_values.pack(side="left", padx=5) # Sejajarkan ke kiri dengan padding



    def create_panduan_calibration_settings_frame(self, parent_frame):
        lbl_title = ctk.CTkLabel(parent_frame, text="Panduan Calibration Settings", font=ctk.CTkFont(size=20, weight="bold"), text_color="#222222")
        lbl_title.pack(pady=(12,30))

        panduan_text = """
        Panduan untuk Calibration Settings:
        1. Masukkan nilai kalibrasi pada kolom "Set Value Calibration".
        2. Nilai ini akan digunakan untuk menyesuaikan pembacaan sensor.
        3. Klik 'Send' untuk mengirim nilai kalibrasi ke perangkat.
        4. Pastikan nilai sudah sesuai dengan prosedur kalibrasi.
        5. Klik 'Check' untuk melihat status kalibrasi perangkat.
        """
        ctk.CTkLabel(parent_frame, text=panduan_text, justify="left", wraplength=450, font=ctk.CTkFont(size=12)).pack(padx=10, pady=10, anchor="w")

    def refresh_data_calibration(self):
        self.update_labels(0.0, 0.0) # Reset labels when page is shown
        # self.show_calibration_status("Ready", text_color="blue") # Reset status

    def update_labels(self, flow, volume):
        self.lbl_flow.configure(text=f"Flowmeter: {flow:.2f}")
        self.lbl_volume.configure(text=f"Volume: {volume:.2f}")

    def update_calibration_loop(self):
        if not self.serial_running:
            return
        while not self.calib_data_queue.empty():
            val = self.calib_data_queue.get()
            if isinstance(val, tuple) and len(val) >= 2 and val[0] != 'error':
                flow = val[0]
                volume = val[1]
                self.update_labels(flow, volume)
        self.after(100, self.update_calibration_loop)

    def zero_tar_clicked(self):
        try:
            ser = serial.Serial(COM_PORT, BAUDRATE , timeout=1)
            ser.write(b"z")
            ser.close()
            messagebox.showinfo("Success", "Zero command sent to Arduino.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send Zero command: {e}")

    def send_calibration_values(self):
        try:
            set_value = int(self.entry_setlow.get())
        except ValueError:
            messagebox.showerror("Validation Error", "Please enter angka untuk Set Value Calibration.")
            return

        data_str = f"{set_value}"
        try:
            ser = serial.Serial(COM_PORT, BAUDRATE, timeout=1)
            ser.write(data_str.encode('ascii'))
            ser.close()
            messagebox.showinfo("Success", f"Calibration command sent to Arduino: \"{data_str}\"")
            # self.show_calibration_status("Calibration command sent!", text_color="green")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send Calibration command: {e}")
            # self.show_calibration_status(f"Error sending command: {e}", text_color="red")

    def start_serial_calibration(self):
        self.stop_serial_calibration()
        self.calib_serial_stop_event.clear()
        self.calib_serial_thread = SerialReader(COM_PORT, BAUDRATE, self.calib_data_queue, self.calib_serial_stop_event)
        self.calib_serial_thread.start()
        self.serial_running = True
        self.after(100, self.update_calibration_loop)  # 🔄 Tambahkan baris ini

    def stop_serial_calibration(self):
        if self.serial_running:
            self.serial_stop_event.set()
            self.calib_serial_thread.join()
            self.serial_running = False

            # 🔧 Reset label ke nilai default
            self.lbl_flow.configure(text="Flowmeter: 0.00")
            self.lbl_volume.configure(text="Volume: 0.00")

class SettingPage(ctk.CTkFrame):

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller

        frame_hosp = ctk.CTkFrame(self)
        frame_hosp.pack(side="top", fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(frame_hosp, text="Hospital Information", font=("Arial", 16, "bold")).pack(pady=6)
        ewrap = ctk.CTkFrame(frame_hosp, fg_color="transparent")
        ewrap.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(ewrap, text="Name:", width=60).pack(side="left")
        self.hosp_name = ctk.CTkEntry(ewrap)
        self.hosp_name.pack(side="left", fill="x", expand=True, padx=(8,0))
        ctk.CTkLabel(ewrap, text="Address:", width=74).pack(side="left", padx=(12, 0))
        self.hosp_addr = ctk.CTkEntry(ewrap)
        self.hosp_addr.pack(side="left", fill="x", expand=True, padx=(8,0))

        hosp_btnwrap = ctk.CTkFrame(frame_hosp, fg_color="transparent")
        hosp_btnwrap.pack(fill="x", padx=10, pady=(3,3))
        btn_add_hosp = ctk.CTkButton(hosp_btnwrap, text="➕ Add", width=85, command=self.add_hospital, font=("Arial", 13, "bold"))
        btn_add_hosp.pack(side="left", padx=(0,4))
        btn_del_hosp = ctk.CTkButton(hosp_btnwrap, text="🗑️ Delete", width=93, command=self.delete_hospital, font=("Arial", 13, "bold"))
        btn_del_hosp.pack(side="left", padx=(4,0))

        ctk.CTkLabel(frame_hosp, text="History Hospital Data", font=("Arial", 13, "bold")).pack(anchor="w", padx=10)
        hosp_table_frame = ctk.CTkFrame(frame_hosp)
        hosp_table_frame.pack(fill="x", padx=10, pady=(0,10))
        self.hosp_table = ttk.Treeview(hosp_table_frame, columns=("No", "Hospital Name", "Address"), show="headings", height=5)
        self.hosp_table.heading("No", text="No")
        self.hosp_table.heading("Hospital Name", text="Hospital Name")
        self.hosp_table.heading("Address", text="Address")
        self.hosp_table.column("No", width=35, anchor="center")
        self.hosp_table.column("Hospital Name", width=170, anchor="center")
        self.hosp_table.column("Address", width=170, anchor="center")
        self.hosp_table.pack(side="left", fill="both", expand=True)
        sb1 = tk.Scrollbar(hosp_table_frame, orient="vertical", command=self.hosp_table.yview)
        sb1.pack(side="right", fill="y")
        self.hosp_table.config(yscrollcommand=sb1.set)

        frame_doc = ctk.CTkFrame(self)
        frame_doc.pack(side="top", fill="x", padx=12, pady=(12, 8))

        ctk.CTkLabel(frame_doc, text="Doctor Information", font=("Arial", 16, "bold")).pack(pady=6)
        dwrap = ctk.CTkFrame(frame_doc, fg_color="transparent")
        dwrap.pack(fill="x", padx=10, pady=3)
        ctk.CTkLabel(dwrap, text="Name:", width=60).pack(side="left")
        self.doc_name = ctk.CTkEntry(dwrap)
        self.doc_name.pack(side="left", fill="x", expand=True, padx=(8,0))

        doc_btnwrap = ctk.CTkFrame(frame_doc, fg_color="transparent")
        doc_btnwrap.pack(fill="x", padx=10, pady=(3,3))
        btn_add_doc = ctk.CTkButton(doc_btnwrap, text="➕ Add", width=85, command=self.add_doctor, font=("Arial", 13, "bold"))
        btn_add_doc.pack(side="left", padx=(0,4))
        btn_del_doc = ctk.CTkButton(doc_btnwrap, text="🗑️ Delete", width=93, command=self.delete_doctor, font=("Arial", 13, "bold"))
        btn_del_doc.pack(side="left", padx=(4,0))

        ctk.CTkLabel(frame_doc, text="History Doctor Data", font=("Arial", 13, "bold")).pack(anchor="w", padx=10)
        doc_table_frame = ctk.CTkFrame(frame_doc)
        doc_table_frame.pack(fill="x", padx=10, pady=(0,6))
        self.doc_table = ttk.Treeview(doc_table_frame, columns=("No", "Doctor Name"), show="headings", height=5)
        self.doc_table.heading("No", text="No")
        self.doc_table.heading("Doctor Name", text="Doctor Name")
        self.doc_table.column("No", width=35, anchor="center")
        self.doc_table.column("Doctor Name", width=240, anchor="center")
        self.doc_table.pack(side="left", fill="both", expand=True)
        sb2 = tk.Scrollbar(doc_table_frame, orient="vertical", command=self.doc_table.yview)
        sb2.pack(side="right", fill="y")
        self.doc_table.config(yscrollcommand=sb2.set)

        self.refresh_hospital()
        self.refresh_doctor()

    def add_hospital(self):
        name = self.hosp_name.get().strip()
        address = self.hosp_addr.get().strip()
        if name and address:
            conn = sqlite3.connect('hospital_doctor.db')
            c = conn.cursor()
            c.execute("INSERT INTO hospitals (name, address) VALUES (?, ?)", (name, address))
            conn.commit()
            conn.close()
            self.refresh_hospital()
            self.hosp_name.delete(0, "end")
            self.hosp_addr.delete(0, "end")

    def delete_hospital(self):
        selected = self.hosp_table.selection()
        if selected:
            idx = self.hosp_table.index(selected[0])
            conn = sqlite3.connect('hospital_doctor.db')
            c = conn.cursor()
            c.execute("SELECT id FROM hospitals ORDER BY id")
            ids = [row[0] for row in c.fetchall()]
            if idx < len(ids):
                c.execute("DELETE FROM hospitals WHERE id=?", (ids[idx],))
                conn.commit()
            conn.close()
            self.refresh_hospital()

    def refresh_hospital(self):
        for item in self.hosp_table.get_children():
            self.hosp_table.delete(item)
        conn = sqlite3.connect('hospital_doctor.db')
        c = conn.cursor()
        c.execute("SELECT name, address FROM hospitals ORDER BY id")
        rows = c.fetchall()
        conn.close()
        for idx, (hosp, addr) in enumerate(rows, start=1):
            self.hosp_table.insert("", "end", values=(idx, hosp, addr))

    def add_doctor(self):
        name = self.doc_name.get().strip()

        if name == "12345":
            self.controller.on_close()
            return

        special_commands = {"R", "F", "B", "C", "T", "X"}
        command_descriptions = {
            "R": "Reset Calibration",
            "F": "Reset Filter",
            "B": "Test Buzzer",
            "C": "Clear EEPROM",
            "T": "Reset Rate Calculation",
            "X": "Reset ALL"
        }
        if name in special_commands:
            try:
                ser = serial.Serial(COM_PORT, BAUDRATE, timeout=1)
                ser.write(name.encode('ascii'))  # kirim sebagai byte
                ser.close()
                # Ambil deskripsi perintah
                desc = command_descriptions.get(name, "Perintah khusus")
                messagebox.showinfo("Serial", f"Perintah '{name}': {desc} berhasil dikirim ke perangkat.")
            except Exception as e:
                messagebox.showerror("Serial Error", f"Gagal mengirim data ke serial: {e}")
            return  # Hentikan proses agar tidak masuk DB

        if name == "11111":
            try:
                os.startfile(".")  # Membuka folder saat ini di File Explorer
                messagebox.showinfo("Explorer", "Windows Explorer berhasil dibuka.")
            except Exception as e:
                messagebox.showerror("Error", f"Gagal membuka Explorer: {e}")
            return

        # Tangani command O<number> atau O-<number> Calibration raw
        if re.fullmatch(r"O-?\d+", name):
            try:
                ser = serial.Serial(COM_PORT, BAUDRATE, timeout=1)
                ser.write(name.encode('ascii'))  # contoh: "O1000" atau "O-500"
                ser.close()
                messagebox.showinfo("Serial", f"Command '{name}' berhasil dikirim ke perangkat.")
            except Exception as e:
                messagebox.showerror("Serial Error", f"Gagal mengirim command '{name}' ke serial: {e}")
            return

        # Tangani command C<number> atau C-<number> calibration factor
        if re.fullmatch(r"C[+-]?\d+", name):
            try:
                ser = serial.Serial(COM_PORT, BAUDRATE, timeout=1)
                ser.write(name.encode('ascii'))  # contoh: "O1000" atau "O-500"
                ser.close()
                messagebox.showinfo("Serial", f"Command '{name}' berhasil dikirim ke perangkat.")
            except Exception as e:
                messagebox.showerror("Serial Error", f"Gagal mengirim command '{name}' ke serial: {e}")
            return

        # Tangani command V<number> atau O-<number> Volume
        if re.fullmatch(r"V[+-]?\d+", name):
            try:
                ser = serial.Serial(COM_PORT, BAUDRATE, timeout=1)
                ser.write(name.encode('ascii'))  # contoh: "O1000" atau "O-500"
                ser.close()
                messagebox.showinfo("Serial", f"Command '{name}' berhasil dikirim ke perangkat.")
            except Exception as e:
                messagebox.showerror("Serial Error", f"Gagal mengirim command '{name}' ke serial: {e}")
            return


        if name == "99999":
            try:
                subprocess.Popen("taskmgr")  # Membuka Task Manager
                messagebox.showinfo("Task Manager", "Task Manager berhasil dibuka.")
            except Exception as e:
                messagebox.showerror("Error", f"Gagal membuka Task Manager: {e}")
            return

        if name:
            conn = sqlite3.connect('hospital_doctor.db')
            c = conn.cursor()
            c.execute("INSERT INTO doctors (name) VALUES (?)", (name,))
            conn.commit()
            conn.close()
            self.refresh_doctor()
            self.doc_name.delete(0, "end")

    def delete_doctor(self):
        selected = self.doc_table.selection()
        if selected:
            idx = self.doc_table.index(selected[0])
            conn = sqlite3.connect('hospital_doctor.db')
            c = conn.cursor()
            c.execute("SELECT id FROM doctors ORDER BY id")
            ids = [row[0] for row in c.fetchall()]
            if idx < len(ids):
                c.execute("DELETE FROM doctors WHERE id=?", (ids[idx],))
                conn.commit()
            conn.close()
            self.refresh_doctor()

    def refresh_doctor(self):
        for item in self.doc_table.get_children():
            self.doc_table.delete(item)
        conn = sqlite3.connect('hospital_doctor.db')
        c = conn.cursor()
        c.execute("SELECT name FROM doctors ORDER BY id")
        rows = c.fetchall()
        conn.close()
        for idx, (doc,) in enumerate(rows, start=1):
            self.doc_table.insert("", "end", values=(idx, doc))

if __name__ == "__main__":
    app = App()
    app.mainloop()
