import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
from datetime import datetime, timezone, timedelta
import threading
import time as t
from plyer import notification
import sys
import os
from pystray import Icon as TrayIcon, Menu as TrayMenu, MenuItem as TrayItem
from PIL import Image

if getattr(sys, 'frozen', False):
    base_path = os.path.dirname(sys.executable)
else:
    base_path = os.path.dirname(__file__)

DB_FILE = os.path.join(base_path, "cartridges.db")
CARTRIDGE_TYPES = ["Black", "Cyan", "Magenta", "Yellow", "Waste"]

class CartridgeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Принтери і картриджі")

        self.conn = sqlite3.connect(DB_FILE)
        self.cursor = self.conn.cursor()
        self.init_db()

        self.build_ui()
        self.tray_icon = None
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.create_tray_icon()
        self.load_printers()

        threading.Thread(target=self.background_checks, daemon=True).start()
        threading.Thread(target=self.daily_reminder, daemon=True).start()

    def init_db(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS printers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS cartridges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                printer_id INTEGER,
                type TEXT,
                quantity INTEGER DEFAULT 0,
                min_threshold INTEGER DEFAULT 1,
                FOREIGN KEY (printer_id) REFERENCES printers(id)
            )
        """)
        self.conn.commit()

    def build_ui(self):
        self.tree = ttk.Treeview(self.root, columns=["Printer"] + CARTRIDGE_TYPES, show="headings")
        self.tree.tag_configure("low", background="#ffcccc")  # червоний фон для принтерів яким потрібно дозамовити картридж
        self.tree.pack(expand=True, fill="both", padx=10, pady=5)

        self.tree.heading("Printer", text="Принтер")
        self.tree.column("Printer", width=120)

        for ctype in CARTRIDGE_TYPES:
            self.tree.heading(ctype, text=ctype)
            self.tree.column(ctype, width=80, anchor="center")

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=5)

        tk.Button(btn_frame, text="Додати принтер", command=self.open_add_printer_window).grid(row=0, column=0, padx=5)
        tk.Button(btn_frame, text="Редагувати кількість", command=self.edit_quantity).grid(row=0, column=1, padx=5)
        tk.Button(btn_frame, text="Відмітити заміну", command=self.mark_replacement).grid(row=0, column=2, padx=5)
        tk.Button(btn_frame, text="Оновити", command=self.load_printers).grid(row=0, column=3, padx=5)
        tk.Button(btn_frame, text="Видалити принтер", command=self.delete_printer).grid(row=0, column=4, padx=5)


    def load_printers(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        self.cursor.execute("SELECT id, name FROM printers")
        printers = self.cursor.fetchall()

        for pid, pname in printers:
            self.cursor.execute(
                "SELECT type, quantity, min_threshold FROM cartridges WHERE printer_id = ?", (pid,))
            cartridges = self.cursor.fetchall()

            cartridge_dict = {}
            low_found = False
            for ctype, qty, min_thresh in cartridges:
                cartridge_dict[ctype] = qty
                if qty < min_thresh:
                    low_found = True

            values = [pname] + [cartridge_dict.get(ctype, 0) for ctype in CARTRIDGE_TYPES]
            tags = ("low",) if low_found else ()
            self.tree.insert("", "end", iid=pid, values=values, tags=tags)

    def hide_window(self):
        self.root.withdraw()

    def show_window(self, icon, item):
        self.root.after(0, self.root.deiconify)

    def quit_app(self, icon, item):
        icon.stop()
        self.root.after(0, self.root.destroy)

    def create_tray_icon(self):
        image = Image.open(os.path.join(getattr(sys, '_MEIPASS', os.path.abspath(".")), 'icon.png'))  # Використай згенеровану іконку
        menu = TrayMenu(
            TrayItem('Відкрити', self.show_window),
            TrayItem('Вийти', self.quit_app)
        )
        self.tray_icon = TrayIcon("CartridgeTracker", image, "Cartridge Tracker", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def center_window(self, window):
        window.update_idletasks()
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        win_w = window.winfo_width()
        win_h = window.winfo_height()
        x = root_x + (root_w - win_w) // 2
        y = root_y + (root_h - win_h) // 2
        window.geometry(f"+{x}+{y}")

    def open_add_printer_window(self):
        top = tk.Toplevel(self.root)
        top.grab_set()
        top.title("Додати принтер")

        tk.Label(top, text="Назва принтера:").grid(row=0, column=0, padx=5, pady=5)
        name_entry = tk.Entry(top)
        name_entry.grid(row=0, column=1, padx=5, pady=5)

        entries = {}
        min_entries = {}
        for idx, ctype in enumerate(CARTRIDGE_TYPES):
            tk.Label(top, text=f"{ctype} кількість:").grid(row=idx + 1, column=0, padx=5, pady=2)
            q_ent = tk.Entry(top, width=5)
            q_ent.insert(0, "0")
            q_ent.grid(row=idx + 1, column=1, padx=5, pady=2)
            entries[ctype] = q_ent

            tk.Label(top, text=f"{ctype} мінімум:").grid(row=idx + 1, column=2, padx=5, pady=2)
            m_ent = tk.Entry(top, width=5)
            m_ent.insert(0, "1")
            m_ent.grid(row=idx + 1, column=3, padx=5, pady=2)
            min_entries[ctype] = m_ent

        def add():
            name = name_entry.get().strip()
            if not name:
                messagebox.showerror("Помилка", "Введіть назву принтера")
                return
            try:
                self.cursor.execute("INSERT INTO printers (name) VALUES (?)", (name,))
                self.conn.commit()
                pid = self.cursor.lastrowid
                for ctype in CARTRIDGE_TYPES:
                    try:
                        q = int(entries[ctype].get())
                    except ValueError:
                        q = 0
                    try:
                        m = int(min_entries[ctype].get())
                    except ValueError:
                        m = 1
                    self.cursor.execute(
                        "INSERT INTO cartridges (printer_id, type, quantity, min_threshold) VALUES (?, ?, ?, ?)",
                        (pid, ctype, q, m))
                self.conn.commit()
                self.load_printers()
                top.destroy()
            except sqlite3.IntegrityError:
                messagebox.showerror("Помилка", "Принтер з такою назвою вже існує")

        tk.Button(top, text="Додати", command=add).grid(row=len(CARTRIDGE_TYPES)+1, columnspan=4, pady=10)
        self.center_window(top)

    def edit_quantity(self):
        selected = self.tree.focus()
        if not selected:
            messagebox.showerror("Помилка", "Оберіть принтер")
            return

        pname = self.tree.item(selected)["values"][0]
        printer_id = int(selected)

        top = tk.Toplevel(self.root)
        top.grab_set()
        top.title(f"Редагувати кількість – {pname}")

        entries = {}
        min_entries = {}
        for idx, ctype in enumerate(CARTRIDGE_TYPES):
            tk.Label(top, text=ctype).grid(row=idx, column=0, padx=5, pady=2, sticky="e")

            ent_q = tk.Entry(top, width=5)
            ent_q.grid(row=idx, column=1, padx=5, pady=2)
            self.cursor.execute(
                "SELECT quantity FROM cartridges WHERE printer_id = ? AND type = ?",
                (printer_id, ctype))
            q = self.cursor.fetchone()
            ent_q.insert(0, q[0] if q else 0)
            entries[ctype] = ent_q

            ent_m = tk.Entry(top, width=5)
            ent_m.grid(row=idx, column=2, padx=5, pady=2)
            self.cursor.execute(
                "SELECT min_threshold FROM cartridges WHERE printer_id = ? AND type = ?",
                (printer_id, ctype))
            m = self.cursor.fetchone()
            ent_m.insert(0, m[0] if m else 1)
            min_entries[ctype] = ent_m

        def save():
            for ctype in CARTRIDGE_TYPES:
                try:
                    q = int(entries[ctype].get())
                    m = int(min_entries[ctype].get())
                    self.cursor.execute(
                        "UPDATE cartridges SET quantity = ?, min_threshold = ? WHERE printer_id = ? AND type = ?",
                        (q, m, printer_id, ctype))
                except ValueError:
                    continue
            self.conn.commit()
            self.load_printers()
            top.destroy()

        tk.Button(top, text="Зберегти", command=save).grid(row=len(CARTRIDGE_TYPES), columnspan=3, pady=10)
        self.center_window(top)

    def mark_replacement(self):
        top = tk.Toplevel(self.root)
        top.grab_set()
        top.title("Відмітити заміну картриджів")

        tk.Label(top, text="Оберіть принтер").pack(pady=5)
        self.cursor.execute("SELECT id, name FROM printers")
        printers = self.cursor.fetchall()
        printer_names = [p[1] for p in printers]

        selected_printer = tk.StringVar()
        combo = ttk.Combobox(top, values=printer_names, state="readonly", textvariable=selected_printer)
        combo.pack(pady=5)
        if printer_names:
            combo.current(0)

        tk.Label(top, text="Оберіть замінені картриджі").pack(pady=5)
        vars_checks = {}
        frame_checks = tk.Frame(top)
        frame_checks.pack()

        for ctype in CARTRIDGE_TYPES:
            var = tk.BooleanVar()
            chk = tk.Checkbutton(frame_checks, text=ctype, variable=var)
            chk.pack(anchor="w")
            vars_checks[ctype] = var

        def save_replacement():
            pname = selected_printer.get()
            if not pname:
                messagebox.showerror("Помилка", "Оберіть принтер")
                return
            printer_id = next((p[0] for p in printers if p[1] == pname), None)
            replaced = [ctype for ctype, var in vars_checks.items() if var.get()]
            if not replaced:
                messagebox.showerror("Помилка", "Оберіть хоча б один картридж")
                return

            for ctype in replaced:
                self.cursor.execute(
                    "SELECT quantity FROM cartridges WHERE printer_id = ? AND type = ?",
                    (printer_id, ctype)
                )
                q = self.cursor.fetchone()
                if q and q[0] > 0:
                    new_q = q[0] - 1
                    self.cursor.execute(
                        "UPDATE cartridges SET quantity = ? WHERE printer_id = ? AND type = ?",
                        (new_q, printer_id, ctype)
                    )
            self.conn.commit()
            self.load_printers()
            top.destroy()

        tk.Button(top, text="Відмітити", command=save_replacement).pack(pady=10)
        self.center_window(top)

    def notify_low_cartridges(self):
        self.cursor.execute("SELECT id, name FROM printers")
        printers = self.cursor.fetchall()

        for pid, pname in printers:
            self.cursor.execute("""
                SELECT type, quantity, min_threshold 
                FROM cartridges 
                WHERE printer_id = ? AND quantity < min_threshold
            """, (pid,))
            low_cartridges = self.cursor.fetchall()
            if low_cartridges:
                types = ", ".join([f"{t}({q})" for t, q, _ in low_cartridges])
                notification.notify(
                    title="Увага! Треба дозамовити картриджі!!!",
                    message=f"Принтер {pname}: \nНизький рівень:\n {types}",
                    app_name="Printer Cartridge App",
                        timeout=10
                )

    def daily_reminder(self):
        while True:
            now = datetime.now(timezone(timedelta(hours=3)))  # UTC+3 = Київ
            if now.hour == 16:
                notification.notify(
                    title="Нагадування",
                    message="Чи оновлювали ви сьогодні картриджі в принтері? Не забудьте внести зміни в трекер!",
                    app_name="Cartridge Tracker",
                    timeout=60
                )
                # чекати 61 секунду, щоб не повторювалося кілька разів
                t.sleep(900)
            else:
                t.sleep(30)


    def background_checks(self):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        while True:
            cursor.execute("SELECT id, name FROM printers")
            printers = cursor.fetchall()
            for pid, pname in printers:
                cursor.execute("""
                    SELECT type, quantity, min_threshold 
                    FROM cartridges 
                    WHERE printer_id = ? AND quantity < min_threshold
                """, (pid,))
                low_cartridges = cursor.fetchall()
                if low_cartridges:
                    types = ", ".join([f"{t}({q})" for t, q, _ in low_cartridges])
                    notification.notify(
                        title="Увага! Треба дозамовити картриджі!!!",
                    message=f"Принтер {pname}: \nНизький рівень:\n {types}",
                    app_name="Printer Cartridge App",
                        timeout=10
                    )
            t.sleep(6000)

    def delete_printer(self):
        selected = self.tree.focus()
        if not selected:
            messagebox.showerror("Помилка", "Оберіть принтер для видалення")
            return

        pname = self.tree.item(selected)["values"][0]
        confirm = messagebox.askyesno("Підтвердження", f"Ви впевнені, що хочете видалити принтер '{pname}'?")
        if confirm:
            printer_id = int(selected)
            self.cursor.execute("DELETE FROM cartridges WHERE printer_id = ?", (printer_id,))
            self.cursor.execute("DELETE FROM printers WHERE id = ?", (printer_id,))
            self.conn.commit()
            self.load_printers()


def main():
    root = tk.Tk()
    root.geometry("650x400")
    app = CartridgeApp(root)
    root.mainloop()
    


if __name__ == "__main__":
    main()

