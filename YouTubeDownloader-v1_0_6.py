import os
import sys
import json
import subprocess
import threading
import time
import random
import re
import webbrowser
import urllib.request
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import messagebox, filedialog, ttk


# --- Έκδοση εφαρμογής & έλεγχος ενημέρωσης ---
APP_VERSION = "1.0.6"  # Αυξάνεται με κάθε νέα έκδοση
VERSION_CHECK_URL = "https://raw.githubusercontent.com/SAKATAKM46/yt-downloader-releases/main/version.json"


def parse_version(v):
    """ '1.0.3' -> (1, 0, 3) για σωστή αριθμητική σύγκριση εκδόσεων """
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)


def check_for_app_update():
    try:
        req = urllib.request.Request(
            VERSION_CHECK_URL, 
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data
    except Exception as e:
        print(f"Error checking update: {e}")
        return None

        
def get_base_dir():
    """ Ο φάκελος όπου βρίσκεται το .exe (ή το .py σε dev mode) — για config.json και bin """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.dirname(__file__))


def get_resource_path(relative_path):
    """ Βρίσκει πόρους (π.χ. icon.ico) που είναι packaged μέσα στο .exe (PyInstaller _MEIPASS) """
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_bin_path(relative_path=""):
    """ Βρίσκει εργαλεία (yt-dlp.exe, ffmpeg.exe) στον φάκελο 'bin' ΔΙΠΛΑ στο .exe """
    return os.path.join(get_base_dir(), "bin", relative_path) if relative_path else os.path.join(get_base_dir(), "bin")


CONFIG_FILE = os.path.join(get_base_dir(), "config.json")


def load_config():
    default_dir = os.path.expanduser("~/Desktop")
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "music_path": data.get("music_path", default_dir),
                    "video_path": data.get("video_path", default_dir),
                    "theme": data.get("theme", "dark"),
                    "last_ytdlp_check": data.get("last_ytdlp_check", "")
                }
        except Exception:
            pass
    return {"music_path": default_dir, "video_path": default_dir, "theme": "dark", "last_ytdlp_check": ""}


def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
    except Exception:
        pass


def add_right_click_paste(widget):
    menu = tk.Menu(widget, tearoff=0)

    def paste():
        try:
            clipboard = widget.clipboard_get()
            if isinstance(widget, tk.Text):
                cursor_pos = widget.index(tk.INSERT)
                line_start = cursor_pos.split(".")[1] == "0"
                current_content = widget.get("1.0", tk.END).strip()
                if current_content and not line_start:
                    widget.insert(tk.INSERT, "\n")
                widget.insert(tk.INSERT, clipboard.strip() + "\n")
            else:
                widget.insert(tk.INSERT, clipboard)
        except tk.TclError:
            pass

    menu.add_command(label="📋 Επικόλληση (Paste)", command=paste)

    def show_menu(event):
        menu.tk_popup(event.x_root, event.y_root)

    widget.bind("<Button-3>", show_menu)


MAX_BATCH_LINKS = 5


def extract_links(raw_text):
    candidates = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r'(?=https?://)', line)
        for p in parts:
            p = p.strip()
            if p:
                candidates.append(p)
    return candidates


def check_tool_available(path, tool_name):
    if not os.path.exists(path):
        return False, f"Δεν βρέθηκε το {tool_name} στη διαδρομή:\n{path}\n\nΒεβαιώσου ότι ο φάκελος 'bin' είναι δίπλα στο πρόγραμμα."
    return True, ""


def download_and_apply_update(download_url):
    if not getattr(sys, 'frozen', False):
        return False, "Η αυτόματη ενημέρωση λειτουργεί μόνο στο packaged .exe, όχι σε dev mode (.py)."
    if os.name != 'nt':
        return False, "Η αυτόματη ενημέρωση υποστηρίζεται μόνο σε Windows."

    current_exe = sys.executable
    new_exe_temp = current_exe + ".new"

    try:
        with urllib.request.urlopen(download_url, timeout=30) as response, open(new_exe_temp, "wb") as out_file:
            out_file.write(response.read())
    except Exception as e:
        return False, f"Αποτυχία λήψης: {e}"

    if not os.path.exists(new_exe_temp) or os.path.getsize(new_exe_temp) < 1024 * 1024:
        return False, "Το ληφθέν αρχείο φαίνεται κατεστραμμένο/ελλιπές."

    batch_path = os.path.join(get_base_dir(), "_apply_update.bat")
    batch_content = f"""@echo off
:: Αρχική αναμονή για να κλείσει πλήρως το exe και να ελευθερωθούν τα DLLs
timeout /t 3 /nobreak >nul

:retry
del "{current_exe}" >nul 2>&1
if exist "{current_exe}" (
    timeout /t 1 /nobreak >nul
    goto retry
)

move /y "{new_exe_temp}" "{current_exe}" >nul

:: Εντολή επανεκκίνησης με καθυστέρηση για να προλάβουν τα Windows να κλείσουν το cmd
timeout /t 1 /nobreak >nul
start "" "{current_exe}"
del "%~f0"
"""
    try:
        with open(batch_path, "w", encoding="utf-8") as f:
            f.write(batch_content)
    except Exception as e:
        return False, f"Αποτυχία δημιουργίας updater script: {e}"

    try:
        subprocess.Popen(["cmd", "/c", batch_path], creationflags=subprocess.CREATE_NO_WINDOW)
        os._exit(0)  # Ακαριαία έξοδος για να ελευθερωθούν τα locks της Python
    except Exception as e:
        return False, f"Αποτυχία εκκίνησης updater: {e}"

    return True, ""


def run_ytdlp_self_update():
    ytdlp_path = get_bin_path("yt-dlp.exe")
    ok, err_msg = check_tool_available(ytdlp_path, "yt-dlp.exe")
    if not ok:
        return False, err_msg
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run([ytdlp_path, "-U"], capture_output=True, text=True, creationflags=flags, timeout=60)
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output.strip()
    except Exception as e:
        return False, str(e)


class DownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Downloader - Custom Edition")
        self.root.geometry("650x610")
        self.root.resizable(False, False)

        self.config = load_config()
        self.container = tk.Frame(self.root)
        self.container.pack(fill="both", expand=True)

        self.current_process = None
        self.cancel_requested = False

        self.show_dashboard()
        self.root.after(1500, self.maybe_auto_update_ytdlp)
        self.root.after(2000, self.check_app_update_silent)

    def check_app_update_silent(self):
        def run():
            update_data = check_for_app_update()
            if update_data and parse_version(update_data.get("version", "0")) > parse_version(APP_VERSION):
                self.root.after(0, lambda: self.prompt_and_apply_update(update_data))
        threading.Thread(target=run, daemon=True).start()

    def prompt_and_apply_update(self, update_info):
        version = update_info.get("version", "?")
        notes = update_info.get("notes", "")
        download_url = update_info.get("download_url", "")

        msg = f"Βρέθηκε νέα έκδοση: v{version} (τρέχουσα: v{APP_VERSION})"
        if notes:
            msg += f"\n\nΤι νέο υπάρχει:\n{notes}"

        if not download_url:
            msg += "\n\n(Δεν βρέθηκε αυτόματο link λήψης — άνοιγμα σελίδας.)"
            if messagebox.askyesno("Νέα Έκδοση Διαθέσιμη", msg):
                url = update_info.get("url", "")
                if url:
                    webbrowser.open(url)
            return

        msg += "\n\nΝα γίνει η ενημέρωση τώρα; Το πρόγραμμα θα κλείσει και θα ξανανοίξει μόνο του."
        if not messagebox.askyesno("Νέα Έκδοση Διαθέσιμη", msg):
            return

        progress_win = tk.Toplevel(self.root)
        progress_win.title("Ενημέρωση...")
        progress_win.geometry("320x100")
        progress_win.resizable(False, False)
        tk.Label(progress_win, text="⏳ Λήψη νέας έκδοσης, παρακαλώ περιμένετε...", pady=20).pack()
        progress_win.grab_set()

        def do_update():
            success, err = download_and_apply_update(download_url)

            def finish():
                if success:
                    self.root.destroy()
                else:
                    progress_win.destroy()
                    messagebox.showerror("Σφάλμα Ενημέρωσης", err)
            self.root.after(0, finish)

        threading.Thread(target=do_update, daemon=True).start()

    def maybe_auto_update_ytdlp(self):
        last_check = self.config.get("last_ytdlp_check", "")
        should_check = True
        if last_check:
            try:
                last_dt = datetime.strptime(last_check, "%Y-%m-%d")
                should_check = datetime.now() - last_dt >= timedelta(days=30)
            except Exception:
                should_check = True

        if not should_check:
            return

        def run():
            success, output = run_ytdlp_self_update()
            self.config["last_ytdlp_check"] = datetime.now().strftime("%Y-%m-%d")
            save_config(self.config)
            if success and ("Updated yt-dlp" in output or ("up to date" not in output.lower() and "already" not in output.lower())):
                self.root.after(0, lambda: messagebox.showinfo(
                    "yt-dlp Ενημερώθηκε", "Το yt-dlp ενημερώθηκε αυτόματα στη νεότερη έκδοση! 🎉"))
        threading.Thread(target=run, daemon=True).start()

    @property
    def c(self):
        if self.config.get("theme") == "light":
            return {"bg": "#f4f4f9", "fg": "#333333", "btn_bg": "#e0e0e0", "btn_fg": "#000", "title_bg": "#dddddd", "lbl_fg": "#555"}
        else:
            return {"bg": "#111111", "fg": "white", "btn_bg": "#222222", "btn_fg": "white", "title_bg": "#111111", "lbl_fg": "gray"}

    def apply_window_theme(self):
        self.root.configure(bg=self.c["bg"])
        self.container.configure(bg=self.c["bg"])

    def clear_container(self):
        for widget in self.container.winfo_children():
            widget.destroy()
        self.apply_window_theme()

    def stop_current_download(self):
        self.cancel_requested = True
        if self.current_process and self.current_process.poll() is None:
            try:
                self.current_process.terminate()
            except Exception:
                pass

    # --- 1. ΚΕΝΤΡΙΚΟ ΜΕΝΟΥ ---
    def show_dashboard(self):
        self.clear_container()
        title_lbl = tk.Label(self.container, text="🚀 MP3 & MP4 DOWNLOADER 🚀", font=("Arial", 16, "bold"), fg="#00FF00", bg=self.c["title_bg"])
        title_lbl.pack(fill="x", ipady=15)

        frame = tk.Frame(self.container, pady=30, bg=self.c["bg"])
        frame.pack()

        tk.Button(frame, text="[1] Τραγούδια MP3", font=("Arial", 12, "bold"), width=28, bg=self.c["btn_bg"], fg=self.c["btn_fg"], command=self.show_music_screen).pack(pady=8)
        tk.Button(frame, text="[2] Βίντεο MP4", font=("Arial", 12, "bold"), width=28, bg=self.c["btn_bg"], fg=self.c["btn_fg"], command=self.show_video_screen).pack(pady=8)
        tk.Button(frame, text="[3] Ρυθμίσεις (Φάκελοι & Θέμα)", font=("Arial", 12, "bold"), width=28, bg=self.c["btn_bg"], fg=self.c["btn_fg"], command=self.show_settings_screen).pack(pady=8)
        tk.Button(frame, text="[4] ❌ Έξοδος Εφαρμογής", font=("Arial", 12, "bold"), width=28, bg="#880000", fg="white", command=self.root.destroy).pack(pady=15)

        footer = tk.Label(self.container, text="Made with 🤪 and Python for USB stick!", font=("Arial", 9), fg=self.c["lbl_fg"], bg=self.c["bg"])
        footer.pack(side="bottom", pady=10)

    # --- 2. ΟΘΟΝΗ ΜΟΥΣΙΚΗΣ ---
    def show_music_screen(self):
        self.clear_container()
        self.cancel_requested = False
        back_btn = tk.Button(self.container, text="⬅️ Πίσω", font=("Arial", 10, "bold"), bg="#444", fg="white", command=self.show_dashboard)
        back_btn.place(x=10, y=565)

        tk.Label(self.container, text="🎵 ΚΑΤΕΒΑΣΜΑ ΜΟΥΣΙΚΗΣ MP3", font=("Arial", 14, "bold"), fg="#00AA00", bg=self.c["bg"]).pack(pady=12)
        tk.Label(self.container, text=f"📂 Φάκελος: {self.config['music_path']}", font=("Arial", 9), fg=self.c["lbl_fg"], bg=self.c["bg"]).pack(pady=2)
        tk.Label(self.container, text=f"🔗 Δώσε έως {MAX_BATCH_LINKS} links — ένα ανά γραμμή (Δεξί κλικ για επικόλληση):", font=("Arial", 10), fg=self.c["fg"], bg=self.c["bg"]).pack(pady=6)

        links_text = tk.Text(self.container, font=("Arial", 10), width=60, height=8, bg="white", fg="black")
        links_text.pack(pady=4)
        links_text.focus()
        add_right_click_paste(links_text)

        status_lbl = tk.Label(self.container, text="", font=("Arial", 10, "bold"), bg=self.c["bg"], wraplength=550, justify="left")
        status_lbl.pack(pady=8)

        progress_bar = ttk.Progressbar(self.container, orient="horizontal", length=450, mode="determinate")
        progress_bar.pack(pady=4)

        speed_lbl = tk.Label(self.container, text="", font=("Arial", 9, "italic"), fg="#0055AA", bg=self.c["bg"])
        speed_lbl.pack(pady=2)

        btn_frame = tk.Frame(self.container, bg=self.c["bg"])
        btn_frame.pack(pady=8)

        download_btn = tk.Button(btn_frame, text="🚀 Λήψη Όλων", font=("Arial", 11, "bold"), bg="#008000", fg="white", width=15)
        download_btn.grid(row=0, column=0, padx=5)

        cancel_btn = tk.Button(btn_frame, text="✖ Ακύρωση", font=("Arial", 10, "bold"), bg="#661111", fg="white", width=12, state="disabled")
        cancel_btn.grid(row=0, column=1, padx=5)

        def normalize_link(link):
            if link.startswith("://"):
                return "https" + link
            elif not link.startswith("http"):
                return "https://" + link
            return link

        def start_batch_download():
            raw_text = links_text.get("1.0", tk.END)
            links = [normalize_link(l) for l in extract_links(raw_text)]
            if not links:
                messagebox.showerror("Σφάλμα", "Δώσε τουλάχιστον ένα link!")
                return
            if len(links) > MAX_BATCH_LINKS:
                messagebox.showerror(
                    "Πολλά Links",
                    f"Βρέθηκαν {len(links)} links, αλλά το όριο είναι {MAX_BATCH_LINKS} τη φορά.\n"
                    f"Αφαίρεσε μερικά και ξαναδοκίμασε."
                )
                return

            ytdlp_path = get_bin_path("yt-dlp.exe")
            ok, err_msg = check_tool_available(ytdlp_path, "yt-dlp.exe")
            if not ok:
                messagebox.showerror("Σφάλμα", err_msg)
                return

            self.cancel_requested = False
            links_text.config(state="disabled")
            download_btn.config(state="disabled", bg="#333333")
            cancel_btn.config(state="normal")
            progress_bar.config(maximum=len(links), value=0)

            ffmpeg_path = get_bin_path()

            def download_one(link):
                output_template = os.path.join(self.config['music_path'], "%(title)s.%(ext)s")
                command = [
                    ytdlp_path, "-x", "--audio-format", "mp3", "--audio-quality", "0",
                    "--ffmpeg-location", ffmpeg_path, "--no-playlist",
                    "--retries", "5", "--fragment-retries", "5",
                    "-o", output_template, link
                ]
                output_lines = []
                try:
                    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore', creationflags=flags)
                    self.current_process = process

                    for line in process.stdout:
                        output_lines.append(line)
                        match_speed = re.search(r'at\s+([^\s]+)', line)
                        if match_speed:
                            spd = match_speed.group(1)
                            self.root.after(0, lambda s=spd: speed_lbl.config(text=f"⚡ Ταχύτητα: {s}"))

                    process.wait()
                    tail = "".join(output_lines[-3:]).strip()
                    return process.returncode == 0, tail
                except Exception as e:
                    return False, str(e)

            def run_batch():
                success_count = 0
                failed_links = []
                MAX_ATTEMPTS = 3

                for i, link in enumerate(links):
                    if self.cancel_requested:
                        break

                    self.root.after(0, lambda: speed_lbl.config(text=""))
                    ok, tail = False, ""

                    for attempt in range(1, MAX_ATTEMPTS + 1):
                        if self.cancel_requested:
                            break

                        attempt_text = f" (προσπάθεια {attempt}/{MAX_ATTEMPTS})" if attempt > 1 else ""
                        self.root.after(0, lambda i=i, a=attempt_text: status_lbl.config(
                            text=f"⏳ Λήψη ({i+1}/{len(links)}){a}...", fg="#0055AA"))

                        ok, tail = download_one(link)
                        if ok:
                            break

                        if attempt < MAX_ATTEMPTS and not self.cancel_requested:
                            wait_time = 8 * attempt
                            self.root.after(0, lambda i=i, w=wait_time: status_lbl.config(
                                text=f"⚠ Απέτυχε ({i+1}/{len(links)}) — αναμονή {w}s πριν ξαναδοκιμάσουμε...", fg="#AA5500"))
                            time.sleep(wait_time)

                    if ok:
                        success_count += 1
                    elif not self.cancel_requested:
                        failed_links.append((link, tail))

                    self.root.after(0, lambda i=i: progress_bar.config(value=i + 1))

                    if i < len(links) - 1 and not self.cancel_requested:
                        time.sleep(random.uniform(4, 9))

                self.current_process = None

                def finish():
                    links_text.config(state="normal")
                    download_btn.config(state="normal", bg="#008000")
                    cancel_btn.config(state="disabled")

                    if self.cancel_requested:
                        status_lbl.config(text=f"⛔ Ακυρώθηκε. Ολοκληρώθηκαν {success_count}/{len(links)}.", fg="#AA5500")
                        return

                    if not failed_links:
                        status_lbl.config(text=f"😎 Όλα έτοιμα! {success_count}/{len(links)} κομμάτια κατέβηκαν επιτυχώς. 🎸", fg="green")
                        links_text.delete("1.0", tk.END)
                    else:
                        fail_summary = "\n".join(f"• {l[:45]}...\n   ↳ {err[:120]}" for l, err in failed_links[:3])
                        status_lbl.config(
                            text=f"⚠ Ολοκληρώθηκε: {success_count}/{len(links)} επιτυχή.\nΑπέτυχαν:\n{fail_summary}",
                            fg="#AA5500"
                        )
                self.root.after(0, finish)

            threading.Thread(target=run_batch, daemon=True).start()

        def cancel_download():
            self.stop_current_download()
            cancel_btn.config(state="disabled")

        download_btn.config(command=start_batch_download)
        cancel_btn.config(command=cancel_download)

    # --- 3. ΟΘΟΝΗ ΒΙΝΤΕΟ ---
    def show_video_screen(self):
        self.clear_container()
        self.cancel_requested = False
        self.formats_list = []

        back_btn = tk.Button(self.container, text="⬅️ Πίσω", font=("Arial", 10, "bold"), bg="#444", fg="white", command=self.show_dashboard)
        back_btn.place(x=10, y=565)

        tk.Label(self.container, text="🎬 ΚΑΤΕΒΑΣΜΑ ΒΙΝΤΕΟ MP4", font=("Arial", 14, "bold"), fg="#0055FF", bg=self.c["bg"]).pack(pady=10)
        tk.Label(self.container, text=f"📂 Φάκελος: {self.config['video_path']}", font=("Arial", 9), fg=self.c["lbl_fg"], bg=self.c["bg"]).pack(pady=1)
        tk.Label(self.container, text="🔗 Δώσε το Link (Δεξί κλικ για επικόλληση):", font=("Arial", 10), fg=self.c["fg"], bg=self.c["bg"]).pack(pady=3)

        link_entry = tk.Entry(self.container, font=("Arial", 10), width=50, bg="white", fg="black")
        link_entry.pack(pady=2)
        link_entry.focus()
        add_right_click_paste(link_entry)

        tk.Label(self.container, text="🔍 Επιλογή Διαθέσιμης Μορφής:", font=("Arial", 9, "bold"), fg=self.c["fg"], bg=self.c["bg"]).pack(pady=5)

        format_frame = tk.Frame(self.container, bg=self.c["bg"])
        format_frame.pack(pady=2)

        scrollbar = tk.Scrollbar(format_frame, orient="vertical")
        self.format_listbox = tk.Listbox(format_frame, font=("Arial", 8), width=75, height=8, yscrollcommand=scrollbar.set, selectmode="single", bg="white", fg="black")
        scrollbar.config(command=self.format_listbox.yview)

        self.format_listbox.pack(side="left", fill="y")
        scrollbar.pack(side="right", fill="y")
        self.format_listbox.insert(tk.END, "--- Δώσε Link και πάτα 'Έλεγχος' ---")

        audio_frame = tk.Frame(self.container, bg=self.c["bg"])
        audio_frame.pack(pady=4)
        tk.Label(audio_frame, text="🎧 Ήχος:", fg=self.c["fg"], bg=self.c["bg"], font=("Arial", 9)).pack(side="left", padx=4)
        AUDIO_MODES = {
            "Μέγιστη Συμβατότητα (AAC/M4A)": "bestaudio[ext=m4a]/bestaudio/best",
            "Καλύτερη Ποιότητα (Opus)": "bestaudio/best",
        }
        audio_mode_var = tk.StringVar(value="Μέγιστη Συμβατότητα (AAC/M4A)")
        audio_combo = ttk.Combobox(audio_frame, textvariable=audio_mode_var, values=list(AUDIO_MODES.keys()), state="readonly", width=28)
        audio_combo.pack(side="left")

        status_lbl = tk.Label(self.container, text="", font=("Arial", 9, "bold"), bg=self.c["bg"], wraplength=550, justify="left")
        status_lbl.pack(pady=3)

        progress_bar = ttk.Progressbar(self.container, orient="horizontal", length=450, mode="determinate")
        progress_bar.pack(pady=2)

        speed_lbl = tk.Label(self.container, text="", font=("Arial", 9, "italic"), fg="#0055AA", bg=self.c["bg"])
        speed_lbl.pack(pady=1)

        def clean_youtube_link(raw_link):
            clean_link = raw_link
            if clean_link.startswith("://"):
                clean_link = "https" + clean_link
            elif not clean_link.startswith("http"):
                clean_link = "https://" + clean_link
            if "shorts/" in clean_link:
                video_id = clean_link.split("shorts/")[1].split("?")[0]
                clean_link = f"https://www.youtube.com/watch?v={video_id}"
            return clean_link

        def check_formats():
            raw_link = link_entry.get().strip()
            if not raw_link:
                messagebox.showerror("Σφάλμα", "Δώσε ένα έγκυρο link!")
                return

            ytdlp_path = get_bin_path("yt-dlp.exe")
            ok, err_msg = check_tool_available(ytdlp_path, "yt-dlp.exe")
            if not ok:
                messagebox.showerror("Σφάλμα", err_msg)
                return

            clean_link = clean_youtube_link(raw_link)
            status_lbl.config(text="⏳ Έλεγχος διαθέσιμων μορφών... Παρακαλώ περιμένετε...", fg="#0055AA")
            self.format_listbox.delete(0, tk.END)
            self.formats_list = []

            def run():
                command = [ytdlp_path, "-F", clean_link]
                try:
                    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    result = subprocess.run(command, capture_output=True, text=True, creationflags=flags)

                    if result.returncode != 0:
                        tail = (result.stderr or result.stdout or "").strip().splitlines()
                        tail_text = "\n".join(tail[-5:])
                        self.root.after(0, lambda: [
                            status_lbl.config(text=f"❌ Σφάλμα ελέγχου:\n{tail_text}", fg="red"),
                            self.format_listbox.insert(tk.END, "Σφάλμα εκτέλεσης — δες το μήνυμα παραπάνω.")
                        ])
                        return

                    lines = result.stdout.splitlines()
                    found = []
                    for line in lines:
                        if any(x in line for x in ["[info]", "[youtube]", "ID", "EXT", "RESOLUTION", "---", "==="]):
                            continue
                        if line.strip():
                            parts = line.split()
                            if len(parts) > 0:
                                found.append((parts[0], line.strip()))

                    def update_list():
                        if not found:
                            self.format_listbox.insert(tk.END, "❌ Δεν βρέθηκαν διαθέσιμες μορφές!")
                            status_lbl.config(text="", fg="black")
                        else:
                            for fmt_code, line in found:
                                self.formats_list.append(fmt_code)
                                self.format_listbox.insert(tk.END, line)
                            status_lbl.config(text="✅ Έλεγχος μορφών ολοκληρώθηκε! Επίλεξε και κατέβασε.", fg="green")
                    self.root.after(0, update_list)
                except Exception as e:
                    self.root.after(0, lambda: [
                        status_lbl.config(text=f"❌ Σφάλμα στον έλεγχο: {e}", fg="red"),
                        self.format_listbox.insert(tk.END, "Σφάλμα εκτέλεσης.")
                    ])

            threading.Thread(target=run, daemon=True).start()

        def start_video_download():
            raw_link = link_entry.get().strip()
            if not raw_link:
                messagebox.showerror("Σφάλμα", "Δώσε ένα έγκυρο link!")
                return

            ytdlp_path = get_bin_path("yt-dlp.exe")
            ok, err_msg = check_tool_available(ytdlp_path, "yt-dlp.exe")
            if not ok:
                messagebox.showerror("Σφάλμα", err_msg)
                return

            clean_link = clean_youtube_link(raw_link)

            selected_indices = self.format_listbox.curselection()
            if not selected_indices:
                messagebox.showerror("Σφάλμα", "Επίλεξε μια μορφή από τη λίστα!")
                return

            selected_index = selected_indices[0]
            if selected_index < 0 or selected_index >= len(self.formats_list):
                messagebox.showerror("Σφάλμα", "Λάθος επιλογή!")
                return

            selected_fmt = self.formats_list[selected_index]
            self.cancel_requested = False
            status_lbl.config(text="⏳ Κατεβαίνει το βίντεο...", fg="#0055AA")
            progress_bar['value'] = 0
            speed_lbl.config(text="")
            dl_btn.config(state="disabled", bg="#333333")
            cancel_btn.config(state="normal")

            def run():
                ffmpeg_path = get_bin_path()
                audio_selector = AUDIO_MODES[audio_mode_var.get()]
                output_template = os.path.join(self.config['video_path'], "%(title)s [%(resolution)s].%(ext)s")
                command = [
                    ytdlp_path, "-f", f"{selected_fmt}+{audio_selector}", "--ffmpeg-location", ffmpeg_path,
                    "--merge-output-format", "mp4", "--no-playlist", "-o", output_template, clean_link
                ]
                output_lines = []
                try:
                    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore', creationflags=flags)
                    self.current_process = process

                    for line in process.stdout:
                        output_lines.append(line)
                        if "%" in line:
                            match_pct = re.search(r'(\d+\.?\d*)%', line)
                            match_speed = re.search(r'at\s+([^\s]+)', line)

                            if match_pct:
                                pct = float(match_pct.group(1))
                                self.root.after(0, lambda p=pct: progress_bar.config(value=p))

                            if match_speed:
                                spd = match_speed.group(1)
                                self.root.after(0, lambda s=spd: speed_lbl.config(text=f"⚡ Ταχύτητα: {s}"))

                    process.wait()

                    if self.cancel_requested:
                        self.root.after(0, lambda: status_lbl.config(text="⛔ Η λήψη ακυρώθηκε.", fg="#AA5500"))
                    elif process.returncode == 0:
                        self.root.after(0, lambda: [
                            status_lbl.config(text="🎬 Έτοιμο το βιντεάκι, πάμε στο επόμενο! 🚀", fg="green"),
                            progress_bar.config(value=100),
                            speed_lbl.config(text="✔ Ολοκληρώθηκε!")
                        ])
                    else:
                        tail = "".join(output_lines[-6:]).strip()
                        self.root.after(0, lambda: status_lbl.config(text=f"❌ Σφάλμα λήψης:\n{tail}", fg="red"))
                except Exception as e:
                    self.root.after(0, lambda: status_lbl.config(text=f"❌ Σφάλμα λήψης: {e}", fg="red"))
                finally:
                    self.current_process = None
                    self.root.after(0, lambda: [
                        dl_btn.config(state="normal", bg="#0055AA"),
                        cancel_btn.config(state="disabled")
                    ])

            threading.Thread(target=run, daemon=True).start()

        def cancel_download():
            self.stop_current_download()
            cancel_btn.config(state="disabled")

        button_frame = tk.Frame(self.container, bg=self.c["bg"])
        button_frame.pack(pady=5)

        tk.Button(button_frame, text="🔎 Έλεγχος Μορφών", font=("Arial", 9), bg="#444", fg="white", width=20, command=check_formats).pack(side="left", padx=5)
        dl_btn = tk.Button(button_frame, text="Κατέβασμα", font=("Arial", 9, "bold"), bg="#0055AA", fg="white", width=18, command=start_video_download)
        dl_btn.pack(side="left", padx=5)
        cancel_btn = tk.Button(button_frame, text="✖ Ακύρωση", font=("Arial", 9, "bold"), bg="#661111", fg="white", width=12, state="disabled", command=cancel_download)
        cancel_btn.pack(side="left", padx=5)

    # --- 4. ΟΘΟΝΗ ΡΥΘΜΙΣΕΩΝ ---
    def show_settings_screen(self):
        self.clear_container()
        back_btn = tk.Button(self.container, text="⬅️ Πίσω", font=("Arial", 10, "bold"), bg="#444", fg="white", command=self.show_dashboard)
        back_btn.place(x=10, y=565)

        tk.Label(self.container, text="⚙️ ΡΥΘΜΙΣΕΙΣ ΣΥΣΤΗΜΑΤΟΣ", font=("Arial", 14, "bold"), fg="#AA5500", bg=self.c["bg"]).pack(pady=20)

        def toggle_theme():
            if self.config.get("theme") == "dark":
                self.config["theme"] = "light"
            else:
                self.config["theme"] = "dark"
            save_config(self.config)
            self.show_settings_screen()

        theme_text = "🌙 Ενεργοποίηση Φωτεινού Θέματος (Light)" if self.config.get("theme") == "dark" else "🌌 Ενεργοποίηση Σκοτεινού Θέματος (Dark)"
        tk.Button(self.container, text=theme_text, width=35, bg=self.c["btn_bg"], fg=self.c["btn_fg"], command=toggle_theme).pack(pady=10)

        # --- Ενημέρωση yt-dlp ---
        last_check = self.config.get("last_ytdlp_check", "")
        check_text = f"(τελευταίος έλεγχος: {last_check})" if last_check else "(δεν έχει ελεγχθεί ποτέ)"
        update_status_lbl = tk.Label(self.container, text=f"🔄 Ενημέρωση λήψης (yt-dlp) {check_text}", font=("Arial", 8), fg=self.c["lbl_fg"], bg=self.c["bg"])
        update_status_lbl.pack(pady=(10, 2))

        update_btn = tk.Button(self.container, text="🔄 Έλεγχος Ενημέρωσης Τώρα", width=35, bg=self.c["btn_bg"], fg=self.c["btn_fg"])
        update_btn.pack(pady=(0, 15))

        def do_manual_update():
            update_btn.config(state="disabled", text="⏳ Έλεγχος...")

            def run():
                success, output = run_ytdlp_self_update()
                self.config["last_ytdlp_check"] = datetime.now().strftime("%Y-%m-%d")
                save_config(self.config)

                def show_result():
                    update_btn.config(state="normal", text="🔄 Έλεγχος Ενημέρωσης Τώρα")
                    if success:
                        if "up to date" in output.lower() or "already" in output.lower():
                            messagebox.showinfo("yt-dlp", "Έχεις ήδη τη νεότερη έκδοση! ✅")
                        else:
                            messagebox.showinfo("yt-dlp", f"Ολοκληρώθηκε:\n\n{output[-400:]}")
                    else:
                        messagebox.showerror("Σφάλμα Ενημέρωσης", output)
                    self.show_settings_screen()
                self.root.after(0, show_result)

            threading.Thread(target=run, daemon=True).start()

        update_btn.config(command=do_manual_update)

        # --- Ενημέρωση της ίδιας της εφαρμογής ---
        app_version_lbl = tk.Label(self.container, text=f"📦 Έκδοση Εφαρμογής: v{APP_VERSION}", font=("Arial", 8), fg=self.c["lbl_fg"], bg=self.c["bg"])
        app_version_lbl.pack(pady=(4, 2))

        app_update_btn = tk.Button(self.container, text="🔍 Έλεγχος Νέας Έκδοσης Εφαρμογής", width=35, bg=self.c["btn_bg"], fg=self.c["btn_fg"])
        app_update_btn.pack(pady=(0, 15))

        def do_manual_app_check():
            app_update_btn.config(state="disabled", text="⏳ Έλεγχος...")

            def run():
                update_data = check_for_app_update()

                def show_result():
                    app_update_btn.config(state="normal", text="🔍 Έλεγχος Νέας Έκδοσης Εφαρμογής")
                    if not update_data:
                        messagebox.showerror("Σφάλμα", "Αποτυχία σύνδεσης στο GitHub για έλεγχο έκδοσης!")
                        return

                    remote_ver = update_data.get("version", "")
                    if parse_version(remote_ver) > parse_version(APP_VERSION):
                        self.prompt_and_apply_update(update_data)
                    else:
                        messagebox.showinfo("Έλεγχος Έκδοσης", f"Έχεις ήδη τη νεότερη έκδοση! (v{APP_VERSION})")

                self.root.after(0, show_result)

            threading.Thread(target=run, daemon=True).start()

        app_update_btn.config(command=do_manual_app_check)

        # --- Επιλογή Φακέλων ---
        m_label = tk.Label(self.container, text=f"🎵 Φάκελος MP3:\n{self.config['music_path']}", font=("Arial", 9), justify="left", fg=self.c["fg"], bg=self.c["bg"])
        m_label.pack(pady=5)

        def change_music_folder():
            new_dir = filedialog.askdirectory()
            if new_dir:
                self.config['music_path'] = new_dir
                save_config(self.config)
                m_label.config(text=f"🎵 Φάκελος MP3:\n{self.config['music_path']}")
        tk.Button(self.container, text="1. Επιλογή αποθήκευσης τραγουδιών", width=35, bg=self.c["btn_bg"], fg=self.c["btn_fg"], command=change_music_folder).pack(pady=5)

        v_label = tk.Label(self.container, text=f"🎬 Φάκελος Βίντεο:\n{self.config['video_path']}", font=("Arial", 9), justify="left", fg=self.c["fg"], bg=self.c["bg"])
        v_label.pack(pady=5)

        def change_video_folder():
            new_dir = filedialog.askdirectory()
            if new_dir:
                self.config['video_path'] = new_dir
                save_config(self.config)
                v_label.config(text=f"🎬 Φάκελος Βίντεο:\n{self.config['video_path']}")
        tk.Button(self.container, text="2. Επιλογή αποθήκευσης βίντεο", width=35, bg=self.c["btn_bg"], fg=self.c["btn_fg"], command=change_video_folder).pack(pady=5)

        def reset_settings():
            default_dir = os.path.expanduser("~/Desktop")
            self.config = {"music_path": default_dir, "video_path": default_dir, "theme": "dark"}
            save_config(self.config)
            messagebox.showinfo("Reset", "Οι ρυθμίσεις επαναφέρθηκαν επιτυχώς!")
            self.show_settings_screen()
        tk.Button(self.container, text="3. Επαναφορά ρυθμίσεων (Reset)", width=35, bg="#AA0000", fg="white", command=reset_settings).pack(pady=20)


if __name__ == "__main__":
    root = tk.Tk()
    app = DownloaderApp(root)
    root.mainloop()