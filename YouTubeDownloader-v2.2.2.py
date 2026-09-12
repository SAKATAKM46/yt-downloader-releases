import os
import sys
import io
import json
import glob
import shutil
import tempfile
import subprocess
import threading
import time
import random
import re
import socket
import webbrowser
import urllib.request
import concurrent.futures
from datetime import datetime, timedelta

import tkinter as tk
from tkinter import messagebox, filedialog, colorchooser, ttk

try:
    from PIL import Image, ImageTk, ImageOps
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

try:
    import pygame
    PYGAME_AVAILABLE = True
except Exception:
    PYGAME_AVAILABLE = False


# ======================================================================
#  Έκδοση εφαρμογής & έλεγχος ενημέρωσης
# ======================================================================
APP_VERSION = "2.2.2"  # Αυξάνεται με κάθε νέα έκδοση
VERSION_CHECK_URL = "https://raw.githubusercontent.com/SAKATAKM46/yt-downloader-releases/main/version.json"

MAX_BATCH_LINKS = 5
PREVIEW_SECONDS = 25          # διάρκεια δείγματος preview πριν το κατέβασμα
FONT_FAMILY = "Segoe UI"      # πέφτει αυτόματα σε default αν δεν υπάρχει στο σύστημα

# ======================================================================
#  Μία μόνο διεργασία («single instance») — αν είναι ήδη ανοιχτή η εφαρμογή, το
#  διπλό-κλικ στο εικονίδιο δεν ανοίγει δεύτερο παράθυρο, απλά φέρνει το υπάρχον
#  μπροστά. Χρησιμοποιούμε ένα τοπικό TCP socket (127.0.0.1) σαν «κλειδαριά»: αν
#  η θύρα είναι ήδη δεσμευμένη, σημαίνει ότι τρέχει ήδη μια διεργασία — της
#  στέλνουμε ένα μικρό μήνυμα και τερματίζουμε αμέσως, ΠΡΙΝ ανοίξουμε δικό μας
#  παράθυρο. Σε αντίθεση με ένα lock-file, ένα TCP socket ΔΕΝ μένει «κολλημένο»
#  αν η εφαρμογή κρασάρει — το λειτουργικό το ελευθερώνει αυτόματα.
# ======================================================================
SINGLE_INSTANCE_PORT = 47656


def acquire_single_instance_lock():
    """ Επιστρέφει (is_primary, sock).
    - is_primary=True, sock=<socket>: είμαστε η μοναδική διεργασία -> άνοιξε κανονικά
      παράθυρο (κράτα το sock ζωντανό όσο τρέχει η εφαρμογή).
    - is_primary=False, sock=None: υπάρχει ήδη ανοιχτή η εφαρμογή και ειδοποιήθηκε να
      έρθει μπροστά -> ΜΗΝ ανοίξεις παράθυρο, τερμάτισε αμέσως.
    Αν δεν μπορέσαμε να ελέγξουμε καθόλου (π.χ. μπλοκαρισμένα sockets από
    firewall/antivirus), προχωράμε σαν να είμαστε primary ώστε να ΜΗΝ εμποδίσουμε
    ποτέ οριστικά το άνοιγμα της εφαρμογής. """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # ΠΡΟΣΟΧΗ: ΕΠΙΤΗΔΕΣ δεν βάζουμε SO_REUSEADDR εδώ. Στα Windows, σε αντίθεση με
        # Linux/Mac, το SO_REUSEADDR δεν κάνει αυτό που νομίζει κανείς -- επιτρέπει σε
        # ΑΛΛΗ διεργασία να κάνει bind() στην ΙΔΙΑ θύρα ΑΚΟΜΑ ΚΙ ΕΝΩ μια πρώτη διεργασία
        # την έχει ήδη δεσμευμένη και "ακούει" σε αυτήν. Αυτό ακριβώς ήταν το bug: κάθε
        # νέα εκκίνηση της εφαρμογής "πετύχαινε" το bind() και νόμιζε ότι ήταν η μοναδική
        # (primary), οπότε άνοιγε συνέχεια νέο παράθυρο αντί να καταλάβει ότι υπάρχει ήδη
        # ανοιχτή η εφαρμογή. Χωρίς SO_REUSEADDR, τα Windows ΗΔΗ εμποδίζουν από μόνα τους
        # δεύτερο bind() σε θύρα που «ακούει» ήδη κάποιος -- αυτό είναι απόλυτα αρκετό για
        # τον μηχανισμό μας. Προσθέτουμε επιπλέον, μόνο στα Windows, το SO_EXCLUSIVEADDRUSE
        # που εγγυάται ρητά αποκλειστική δέσμευση της θύρας (καμία άλλη διεργασία δεν
        # μπορεί να την «κλέψει» με κανέναν τρόπο, ό,τι socket option κι αν βάλει).
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        s.listen(5)
        return True, s
    except OSError:
        try:
            client = socket.create_connection(("127.0.0.1", SINGLE_INSTANCE_PORT), timeout=1.5)
            client.sendall(b"SHOW")
            client.close()
            return False, None
        except Exception:
            # Η θύρα φαίνεται δεσμευμένη αλλά δεν απαντάει κανείς (πιθανό «στοιχειωμένο»
            # υπόλειμμα) -> ανοίγουμε κανονικά αντί να μπλοκάρουμε την εφαρμογή.
            return True, None
    except Exception:
        return True, None


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
        base_path = os.path.abspath(os.path.dirname(__file__))
    return os.path.join(base_path, relative_path)


def get_bin_path(relative_path=""):
    """ Βρίσκει εργαλεία (yt-dlp.exe, ffmpeg.exe) στον φάκελο 'bin' ΔΙΠΛΑ στο .exe """
    return os.path.join(get_base_dir(), "bin", relative_path) if relative_path else os.path.join(get_base_dir(), "bin")


def get_preview_dir():
    d = os.path.join(tempfile.gettempdir(), "ytdl_custom_previews")
    os.makedirs(d, exist_ok=True)
    return d


def clear_preview_cache():
    """ Καθαρισμός παλιών προεπισκοπήσεων (best effort, δεν πρέπει ποτέ να ρίξει την εφαρμογή) """
    try:
        d = get_preview_dir()
        for f in glob.glob(os.path.join(d, "*")):
            try:
                os.remove(f)
            except Exception:
                pass
    except Exception:
        pass


def _dir_is_writable(path):
    """ Δοκιμάζει πραγματικά να γράψει (όχι μόνο os.access — στα Windows/Program Files
    το os.access μπορεί να λέει 'ναι' ενώ η εγγραφή αποτυγχάνει λόγω UAC/δικαιωμάτων). """
    try:
        os.makedirs(path, exist_ok=True)
        test_path = os.path.join(path, ".write_test.tmp")
        with open(test_path, "w") as f:
            f.write("x")
        os.remove(test_path)
        return True
    except Exception:
        return False


def get_config_dir():
    """ Φορητή λειτουργία (USB stick / φάκελος με δικαιώματα εγγραφής): το config.json
    μένει ΔΙΠΛΑ στο .exe, όπως πάντα. Αν όμως ο φάκελος δεν είναι εγγράψιμος — π.χ. όταν
    η εφαρμογή είναι εγκατεστημένη μέσα στο Program Files μέσω Inno Setup, όπου
    χρειάζονται δικαιώματα διαχειριστή — πέφτουμε αυτόματα σε φάκελο του χρήστη
    (%APPDATA%\\YTDownloader στα Windows), ώστε οι ρυθμίσεις να αποθηκεύονται πάντα. """
    base = get_base_dir()
    if _dir_is_writable(base):
        return base
    appdata = os.getenv("APPDATA") or os.getenv("XDG_CONFIG_HOME") or os.path.expanduser("~")
    fallback = os.path.join(appdata, "YTDownloader")
    try:
        os.makedirs(fallback, exist_ok=True)
    except Exception:
        pass
    return fallback


CONFIG_DIR = get_config_dir()
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
# True όταν τρέχουμε από εγγράψιμο φάκελο δίπλα στο .exe (φορητή λειτουργία) — χρησιμοποιείται
# ώστε ο αυτόματος updater να ΜΗΝ προσπαθήσει να αντικαταστήσει το .exe όταν είναι
# εγκατεστημένο σε προστατευμένο φάκελο (π.χ. Program Files) χωρίς δικαιώματα εγγραφής.
IS_WRITABLE_INSTALL = (CONFIG_DIR == get_base_dir())

DEFAULT_CONFIG = {
    "music_path": os.path.expanduser("~/Desktop"),
    "video_path": os.path.expanduser("~/Desktop"),
    "theme": "dark",
    "last_ytdlp_check": "",
    "language": "el",           # "el" ή "en"
    "accent_color": "",         # κενό = προεπιλεγμένη παλέτα χρωμάτων
    "window_geometry": "",      # π.χ. "760x680+120+80" — κενό = προεπιλογή/κεντραρισμένο
    "audio_format": "mp3",      # mp3 / m4a / wav / flac / ogg
    "audio_bitrate": "0",       # "0" = βέλτιστο (VBR) · αλλιώς "128"/"192"/"256"/"320"
    "audio_samplerate": "",     # κενό = όπως η πηγή · αλλιώς "44100"/"48000"
    "auto_check_app_update": True,  # έλεγχος για νέα έκδοση εφαρμογής στην εκκίνηση
    "auto_update_ytdlp": True,      # αυτόματη ενημέρωση yt-dlp (προτείνεται — απαραίτητο)
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg = dict(DEFAULT_CONFIG)
                cfg.update({k: data.get(k, v) for k, v in DEFAULT_CONFIG.items()})
                return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
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
                current_content = widget.get("1.0", tk.END).strip()
                cursor_pos = widget.index(tk.INSERT)
                line_start = cursor_pos.split(".")[1] == "0"
                if current_content and not line_start and not current_content.endswith("\n"):
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
    return menu


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


def normalize_link(link):
    link = link.strip()
    if link.startswith("://"):
        return "https" + link
    if not re.match(r'^https?://', link):
        return "https://" + link
    return link


def check_tool_available(path, tool_name):
    if not os.path.exists(path):
        return False, (f"Δεν βρέθηκε το {tool_name} στη διαδρομή:\n{path}\n\n"
                        f"Βεβαιώσου ότι ο φάκελος 'bin' είναι δίπλα στο πρόγραμμα.")
    return True, ""


# ======================================================================
#  Γενίκευση πλατφορμών — ό,τι υποστηρίζει το yt-dlp, όχι μόνο YouTube
# ======================================================================
PLATFORM_ICONS = [
    (("youtube.com", "youtu.be"), "YouTube", "▶️"),
    (("soundcloud.com",), "SoundCloud", "☁️"),
    (("vimeo.com",), "Vimeo", "🎥"),
    (("tiktok.com",), "TikTok", "🎵"),
    (("facebook.com", "fb.watch"), "Facebook", "📘"),
    (("instagram.com",), "Instagram", "📷"),
    (("twitter.com", "x.com"), "X / Twitter", "🐦"),
    (("dailymotion.com",), "Dailymotion", "🎬"),
    (("bandcamp.com",), "Bandcamp", "🎧"),
    (("twitch.tv",), "Twitch", "🎮"),
    (("mixcloud.com",), "Mixcloud", "🔊"),
    (("vk.com",), "VK", "🔵"),
]


def is_youtube_link(link):
    host = _host_of(link)
    return "youtube.com" in host or "youtu.be" in host


def _host_of(link):
    try:
        return re.sub(r'^https?://(www\.)?', '', link, flags=re.I).split('/')[0].lower()
    except Exception:
        return ""


def guess_platform(link):
    host = _host_of(link)
    for domains, name, icon in PLATFORM_ICONS:
        if any(d in host for d in domains):
            return name, icon
    return (host or "Άγνωστη πηγή"), "🌐"


def clean_link(raw_link):
    """ Καθαρίζει/κανονικοποιεί ένα link. Ειδικές διορθώσεις (π.χ. Shorts) γίνονται
    ΜΟΝΟ αν είναι πράγματι YouTube link — δεν επηρεάζουν καμία άλλη πλατφόρμα. """
    link = normalize_link(raw_link)
    if is_youtube_link(link) and "/shorts/" in link:
        try:
            video_id = link.split("shorts/")[1].split("?")[0].split("/")[0]
            if video_id:
                link = f"https://www.youtube.com/watch?v={video_id}"
        except Exception:
            pass
    return link


def human_filesize(n):
    if not n:
        return "—"
    try:
        n = float(n)
    except Exception:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def human_duration(seconds):
    if not seconds and seconds != 0:
        return "—"
    try:
        seconds = int(seconds)
    except Exception:
        return "—"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def run_flags():
    return subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def open_path_with_default_app(path):
    """ Ανοίγει ένα αρχείο/φάκελο με την προεπιλεγμένη εφαρμογή του συστήματος. """
    try:
        if os.name == 'nt':
            os.startfile(path)  # noqa
        elif sys.platform == 'darwin':
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True, ""
    except Exception as e:
        return False, str(e)


# ======================================================================
#  Ανάκτηση metadata (τίτλος / εξώφυλλο / μορφές) — χωρίς κατέβασμα
# ======================================================================
class MetadataError(Exception):
    pass


def fetch_metadata(ytdlp_path, link, timeout=30):
    command = [ytdlp_path, "-j", "--no-playlist", "--skip-download",
               "--no-warnings", clean_link(link)]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                 encoding="utf-8", errors="ignore",
                                 creationflags=run_flags(), timeout=timeout)
    except subprocess.TimeoutExpired:
        raise MetadataError("Λήξη χρονικού ορίου — δοκίμασε ξανά.")
    except Exception as e:
        raise MetadataError(str(e))

    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "Άγνωστο σφάλμα").strip().splitlines()
        raise MetadataError(tail[-1] if tail else "Αποτυχία ανάλυσης link")

    out = (result.stdout or "").strip()
    if not out:
        raise MetadataError("Άδεια απάντηση από yt-dlp.")

    # Το yt-dlp τυπώνει ένα JSON object ανά γραμμή· κρατάμε την πρώτη έγκυρη.
    data = None
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            break
        except Exception:
            continue
    if data is None:
        raise MetadataError("Δεν ήταν δυνατή η ανάγνωση των στοιχείων.")

    return {
        "title": data.get("title") or link,
        "thumbnail": data.get("thumbnail"),
        "duration": data.get("duration"),
        "uploader": data.get("uploader") or data.get("channel") or "",
        "webpage_url": data.get("webpage_url") or link,
        "formats": data.get("formats") or [],
        "id": data.get("id"),
    }


# ======================================================================
#  Εικόνες / εξώφυλλα (thumbnails)
# ======================================================================
_THUMB_CACHE = {}


def download_thumbnail_pil(url, size=(56, 56)):
    """ Τρέχει σε background thread: κατεβάζει + κάνει resize. ΔΕΝ αγγίζει Tk. """
    if not url or not PIL_AVAILABLE:
        return None
    key = (url, size)
    if key in _THUMB_CACHE:
        cached = _THUMB_CACHE[key]
        return cached if not isinstance(cached, ImageTk.PhotoImage) else cached
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img = ImageOps.fit(img, size, method=Image.LANCZOS)
        _THUMB_CACHE[key] = img
        return img
    except Exception:
        return None


def pil_to_photo(pil_image):
    """ ΠΡΕΠΕΙ να τρέχει στο main thread (Tk). """
    if pil_image is None or not PIL_AVAILABLE:
        return None
    try:
        return ImageTk.PhotoImage(pil_image)
    except Exception:
        return None


# ======================================================================
#  Ήχος — αναπαραγωγή τοπικών αρχείων (ήδη κατεβασμένα ή δείγμα preview)
# ======================================================================
class AudioPlayer:
    def __init__(self):
        self.available = False
        self.current_path = None
        self.paused = False
        self.on_state_change = None  # optional callback(path_or_None, playing_bool)
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.init()
                self.available = True
            except Exception:
                self.available = False

    def play(self, path):
        if not self.available:
            return False, "Η αναπαραγωγή ήχου δεν είναι διαθέσιμη σε αυτή τη συσκευή."
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            self.current_path = path
            self.paused = False
            self._notify()
            return True, ""
        except Exception as e:
            return False, f"Αποτυχία αναπαραγωγής: {e}"

    def toggle_pause(self):
        if not self.available or not self.current_path:
            return
        if self.paused:
            pygame.mixer.music.unpause()
            self.paused = False
        else:
            pygame.mixer.music.pause()
            self.paused = True
        self._notify()

    def stop(self):
        if self.available:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self.current_path = None
        self.paused = False
        self._notify()

    def is_playing(self, path=None):
        if not self.available or not self.current_path:
            return False
        if path and os.path.abspath(path) != os.path.abspath(self.current_path):
            return False
        try:
            return pygame.mixer.music.get_busy() and not self.paused
        except Exception:
            return False

    def _notify(self):
        if self.on_state_change:
            try:
                self.on_state_change(self.current_path, self.is_playing())
            except Exception:
                pass


def download_preview_clip(ytdlp_path, ffmpeg_path, link, seconds=PREVIEW_SECONDS):
    """ Κατεβάζει ένα ΜΙΚΡΟ δείγμα ήχου (τα πρώτα ~N δευτερόλεπτα) σε temp φάκελο,
    ώστε να παίξει τοπικά. Πραγματικό κατέβασμα μικρής διάρκειας — όχι ψεύτικο streaming. """
    dest_dir = get_preview_dir()
    stamp = str(int(time.time() * 1000))
    out_template = os.path.join(dest_dir, f"preview_{stamp}_%(id)s.%(ext)s")
    command = [
        ytdlp_path, "-x", "--audio-format", "mp3", "--audio-quality", "6",
        "--ffmpeg-location", ffmpeg_path, "--no-playlist", "--no-warnings",
        "--download-sections", f"*0-{seconds}", "--force-keyframes-at-cuts",
        "-o", out_template, clean_link(link),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                 encoding="utf-8", errors="ignore",
                                 creationflags=run_flags(), timeout=90)
    except subprocess.TimeoutExpired:
        raise MetadataError("Λήξη χρόνου κατά τη λήψη δείγματος.")
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        raise MetadataError(tail[-1] if tail else "Αποτυχία λήψης δείγματος.")

    candidates = sorted(glob.glob(os.path.join(dest_dir, f"preview_{stamp}_*.mp3")),
                         key=os.path.getmtime)
    if not candidates:
        raise MetadataError("Δεν βρέθηκε το αρχείο δείγματος μετά τη λήψη.")
    return candidates[-1]


# ======================================================================
#  Αυτόματη ενημέρωση εφαρμογής / yt-dlp
# ======================================================================
def download_and_apply_update(download_url):
    if not getattr(sys, 'frozen', False):
        return False, "Η αυτόματη ενημέρωση λειτουργεί μόνο στο packaged .exe, όχι σε dev mode (.py)."
    if os.name != 'nt':
        return False, "Η αυτόματη ενημέρωση υποστηρίζεται μόνο σε Windows."
    if not _dir_is_writable(get_base_dir()):
        return False, ("Ο φάκελος του προγράμματος δεν είναι εγγράψιμος από εδώ (π.χ. εγκατάσταση "
                        "μέσα στο Program Files) — η αυτόματη αντικατάσταση του .exe χρειάζεται "
                        "δικαιώματα διαχειριστή. Άνοιξε το πρόγραμμα ως διαχειριστής, ή κατέβασε "
                        "και εγκατέστησε τη νέα έκδοση κανονικά από τη σελίδα λήψης.")

    current_exe = sys.executable
    new_exe_temp = current_exe + ".new"

    try:
        with urllib.request.urlopen(download_url, timeout=30) as response, open(new_exe_temp, "wb") as out_file:
            shutil.copyfileobj(response, out_file)
    except Exception as e:
        return False, f"Αποτυχία λήψης: {e}"

    if not os.path.exists(new_exe_temp) or os.path.getsize(new_exe_temp) < 1024 * 1024:
        try:
            os.remove(new_exe_temp)
        except Exception:
            pass
        return False, "Το ληφθέν αρχείο φαίνεται κατεστραμμένο/ελλιπές."

    # ΣΗΜΑΝΤΙΚΟ: κάνουμε rename το τρέχον .exe σε .bak αντί να το διαγράφουμε πρώτα.
    # Αν κάτι πάει στραβό στο move του νέου, το .bak ξαναγίνεται .exe — έτσι ο χρήστης
    # δεν μένει ποτέ χωρίς πρόγραμμα.
    batch_path = os.path.join(get_base_dir(), "_apply_update.bat")
    backup_exe = current_exe + ".bak"
    batch_content = f"""@echo off
timeout /t 3 /nobreak >nul

if exist "{backup_exe}" del "{backup_exe}" >nul 2>&1

:retry_rename
move /y "{current_exe}" "{backup_exe}" >nul 2>&1
if exist "{current_exe}" (
    timeout /t 1 /nobreak >nul
    goto retry_rename
)

move /y "{new_exe_temp}" "{current_exe}" >nul
if not exist "{current_exe}" (
    move /y "{backup_exe}" "{current_exe}" >nul
    echo Update failed, restored previous version.
    del "%~f0"
    exit /b 1
)

del "{backup_exe}" >nul 2>&1
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
        try:
            for widget in tk._default_root.winfo_children() if tk._default_root else []:
                try:
                    widget.destroy()
                except Exception:
                    pass
        except Exception:
            pass
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
        result = subprocess.run([ytdlp_path, "-U"], capture_output=True, text=True,
                                 creationflags=run_flags(), timeout=60)
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output.strip()
    except Exception as e:
        return False, str(e)


# ======================================================================
#  Μικρά, επαναχρησιμοποιήσιμα UI στοιχεία
# ======================================================================
class ScrollableFrame(tk.Frame):
    """ Frame με κάθετο scroll.

    Δύο τρόποι λειτουργίας:
    - fill_parent=True: ΓΕΜΙΖΕΙ όποιον χώρο του δίνει ο γονιός (π.χ. ολόκληρη η οθόνη)
      και εμφανίζει scrollbar ΜΟΝΟ όταν το περιεχόμενο ξεπερνάει τον πραγματικό
      διαθέσιμο χώρο — έτσι όταν αλλάζει μέγεθος το παράθυρο, τα κουμπιά ΔΕΝ χάνονται
      ποτέ χωρίς τρόπο να φτάσεις εκεί. Χρησιμοποιείται για ολόκληρες οθόνες.
    - fill_parent=False (προεπιλογή): σταθερό μέγιστο ύψος (max_height) — για μικρές
      λίστες μέσα σε μια ήδη μεγαλύτερη οθόνη (π.χ. πίνακας μορφών βίντεο). """

    def __init__(self, parent, bg, max_height=260, fill_parent=False, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=bg)
        self.max_height = max_height
        self.fill_parent = fill_parent

        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")

        self.canvas.bind("<Enter>", lambda e: self._bind_mousewheel())
        self.canvas.bind("<Leave>", lambda e: self._unbind_mousewheel())

    def _on_body_configure(self, event=None):
        bbox = self.canvas.bbox("all")
        if self.fill_parent:
            # Το ύψος του canvas το ορίζει ο γονιός (fill+expand) — εδώ μόνο ενημερώνουμε
            # την scrollregion, ώστε να μπορείς πάντα να κατεβάσεις scroll μέχρι το τέλος,
            # όσο κι αν αλλάξει μέγεθος το παράθυρο.
            self.canvas.configure(scrollregion=bbox)
            return
        height = min(self.max_height, (bbox[3] if bbox else 0))
        height = max(height, 1)
        self.canvas.configure(scrollregion=bbox, height=height)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self._window, width=event.width)

    def _bind_mousewheel(self):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        if getattr(event, "num", None) == 4:
            self.canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self.canvas.yview_scroll(1, "units")
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()


def bind_hover(widget, normal_bg, hover_bg):
    def on_enter(_e):
        try:
            if str(widget["state"]) != "disabled":
                widget.configure(bg=hover_bg)
        except Exception:
            pass

    def on_leave(_e):
        try:
            if str(widget["state"]) != "disabled":
                widget.configure(bg=normal_bg)
        except Exception:
            pass

    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)


def _shade_hex(hex_color, factor):
    """ factor > 1 -> πιο ανοιχτό, factor < 1 -> πιο σκούρο. Μικρό αυτόνομο βοηθητικό
    (ξεχωριστό από τα ίδια-λογικής static methods των κλάσεων παρακάτω) ώστε να το
    χρησιμοποιεί ελεύθερα και το bind_hover_dynamic χωρίς εξάρτηση σε instance. """
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r = min(255, max(0, int(r * factor)))
        g = min(255, max(0, int(g * factor)))
        b = min(255, max(0, int(b * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


def bind_hover_dynamic(widget, shade_factor=0.85):
    """ Ίδιο σκοπό με το bind_hover, αλλά για κουμπιά που το bg τους αλλάζει ΔΥΝΑΜΙΚΑ
    μετά τη δημιουργία τους (π.χ. το κουμπί Play/Pause, που γίνεται μπλε/πορτοκαλί
    ανάλογα με την κατάσταση αναπαραγωγής).

    ΠΡΟΣΟΧΗ (2ο bug που διορθώθηκε εδώ): μια πρώτη εκδοχή αυτής της συνάρτησης
    αποθήκευε το «χρώμα επιστροφής» ΜΟΝΟ τη στιγμή του <Enter> (όταν μπαίνει το ποντίκι
    πάνω στο κουμπί). Αυτό χαλάει ακριβώς όταν το χρώμα αλλάζει ΕΝΩ το ποντίκι είναι ήδη
    πάνω στο κουμπί — π.χ. πατάς το κουμπί (το ποντίκι είναι ήδη «μέσα» από πριν, άρα δεν
    ξαναπυροδοτείται <Enter>), το χρώμα αλλάζει σωστά, αλλά όταν μετά φύγει το ποντίκι το
    <Leave> το γυρνάει πίσω στο ΠΑΛΙΟ (πριν το κλικ) χρώμα, όχι στο νέο.
    Η λύση: το «χρώμα ηρεμίας» (χωρίς hover) κρατιέται σε widget._rest_bg, και το
    ενημερώνει ΚΑΘΕ φορά που αλλάζει η λογική κατάσταση του κουμπιού (βλ.
    _set_play_button_state) — όχι μόνο στο <Enter>. Το <Enter>/<Leave> εδώ απλά
    σκουραίνουν/επαναφέρουν γύρω από αυτή την τρέχουσα «αλήθεια», ό,τι κι αν είναι. """
    if not hasattr(widget, "_rest_bg"):
        try:
            widget._rest_bg = widget.cget("bg")
        except Exception:
            widget._rest_bg = None

    def on_enter(_e):
        try:
            if str(widget["state"]) == "disabled":
                return
            base = getattr(widget, "_rest_bg", None) or widget.cget("bg")
            widget.configure(bg=_shade_hex(base, shade_factor))
        except Exception:
            pass

    def on_leave(_e):
        try:
            if str(widget["state"]) == "disabled":
                return
            base = getattr(widget, "_rest_bg", None)
            if base:
                widget.configure(bg=base)
        except Exception:
            pass

    widget.bind("<Enter>", on_enter)
    widget.bind("<Leave>", on_leave)


class GradientProgressBar(tk.Canvas):
    """ Custom μπάρα προόδου (χωρίς εξάρτηση από ttk theme) με «γυαλιστερή» / 3D
    εμφάνιση: στρογγυλεμένη «χάπι» φόρμα, sunken trough με bevel γραμμές, και
    ανοιχτόχρωμη λωρίδα «γυαλάδας» πάνω στο γέμισμα. Το χρώμα accent μπορεί να
    αλλάξει ελεύθερα ώστε να ακολουθεί τα νέα σημασιολογικά χρώματα κατάστασης
    (αναμονή/λήψη/ολοκλήρωση) ή το προσαρμοσμένο accent χρώμα της εφαρμογής. """

    def __init__(self, parent, width=300, height=16, bg="#1e1e1e", trough="#2a2a2a",
                 accent="#3b82f6", maximum=100, value=0, **kwargs):
        super().__init__(parent, width=width, height=height, bg=bg,
                          highlightthickness=0, bd=0, **kwargs)
        self.trough_color = trough
        self.accent = accent
        self._maximum = max(1, maximum)
        self._value = max(0, value)
        self.bind("<Configure>", lambda _e: self._redraw())
        self._redraw()

    @staticmethod
    def _shade(hex_color, factor):
        """ factor > 1 -> πιο ανοιχτό, factor < 1 -> πιο σκούρο. """
        h = hex_color.lstrip("#")
        if len(h) != 6:
            return hex_color
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r = min(255, max(0, int(r * factor)))
        g = min(255, max(0, int(g * factor)))
        b = min(255, max(0, int(b * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _round_rect(self, x1, y1, x2, y2, radius, **kwargs):
        radius = max(0.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    def set(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0
        self._value = max(0, min(self._maximum, value))
        self._redraw()

    def get(self):
        return self._value

    def configure(self, **kwargs):
        redraw = False
        if "maximum" in kwargs:
            self._maximum = max(1, kwargs.pop("maximum"))
            redraw = True
        if "accent" in kwargs:
            self.accent = kwargs.pop("accent")
            redraw = True
        if "trough" in kwargs:
            self.trough_color = kwargs.pop("trough")
            redraw = True
        if kwargs:
            super().configure(**kwargs)
        if redraw:
            self._redraw()

    config = configure

    def _redraw(self):
        self.delete("all")
        try:
            w = self.winfo_width()
            h = self.winfo_height()
        except Exception:
            return
        if w < 4 or h < 4:
            w = w or int(self["width"])
            h = h or int(self["height"])
        if w < 4 or h < 4:
            return
        radius = h / 2.0

        # Sunken trough: γεμάτο σκούρο φόντο + λεπτές bevel γραμμές (σκούρα πάνω,
        # ανοιχτόχρωμη κάτω) ώστε να δείχνει «βυθισμένο».
        self._round_rect(0, 0, w, h, radius, fill=self.trough_color, outline="")
        inset = max(radius * 0.35, 2)
        self.create_line(inset, 1, w - inset, 1, fill=self._shade(self.trough_color, 0.55), width=1)
        self.create_line(inset, h - 1, w - inset, h - 1, fill=self._shade(self.trough_color, 1.5), width=1)

        ratio = (self._value / self._maximum) if self._maximum else 0.0
        ratio = max(0.0, min(1.0, ratio))
        fill_w = ratio * w
        if fill_w < 2:
            return

        base = self._shade(self.accent, 0.9)
        self._round_rect(0, 0, fill_w, h, radius, fill=base, outline="")
        # Λωρίδα «γυαλάδας» στο πάνω μισό για 3D/glossy εντύπωση.
        highlight = self._shade(self.accent, 1.45)
        self._round_rect(0, 1, fill_w, max(2, h * 0.5), radius * 0.85, fill=highlight, outline="")
        # Λεπτή πιο σκούρα γραμμή στο κάτω άκρο του γεμίσματος για βάθος.
        shadow = self._shade(self.accent, 0.65)
        self.create_line(radius * 0.3, h - 1.5, fill_w - radius * 0.3, h - 1.5, fill=shadow, width=1)


# ======================================================================
#  Μεταφράσεις (Ελληνικά / English)
# ======================================================================
TRANSLATIONS = {
    "el": {
        # -- Κοινά --
        "app_title": "YouTube & Πολλαπλών Πηγών Downloader",
        "back": "⬅  Πίσω",
        "error_title": "Σφάλμα",
        "clear_btn": "🧹 Καθαρισμό",

        # -- Dashboard --
        "dashboard_title": "🚀 Media Downloader",
        "dashboard_subtitle": "MP3 • MP4 • YouTube, SoundCloud, TikTok, Vimeo & άλλα",
        "dashboard_music_title": "Τραγούδια MP3",
        "dashboard_music_desc": "Κατέβασμα ήχου σε MP3 — έως 5 κομμάτια, με προεπισκόπηση εξωφύλλου.",
        "dashboard_video_title": "Βίντεο MP4",
        "dashboard_video_desc": "Κατέβασμα βίντεο με επιλογή ανάλυσης/μορφής και προεπισκόπηση.",
        "dashboard_settings_title": "Ρυθμίσεις",
        "dashboard_settings_desc": "Θέμα εμφάνισης, φάκελοι αποθήκευσης, ενημερώσεις.",
        "dashboard_exit_title": "Έξοδος",
        "dashboard_exit_desc": "Κλείσιμο της εφαρμογής.",
        "dashboard_footer": "v{version}  •  Made with 🤪 and Python — φορητό, τρέχει από USB",

        # -- Μουσική --
        "music_header_title": "🎵 Λήψη Μουσικής",
        "music_subtitle": "📂 Αποθήκευση σε: {path}",
        "music_instructions": "Επικόλλησε ένα ή περισσότερα links (έως {max} συνολικά στην ουρά) από "
                               "YouTube, SoundCloud, Bandcamp κ.ά. — δεξί κλικ για επικόλληση.",
        "music_analyze_btn": "🔎 Ανάλυση Links",
        "music_analyzing_btn": "⏳ Ανάλυση...",
        "music_reset_btn": "🧹 Νέα Λίστα",
        "music_queue_label": "Ουρά τραγουδιών:",
        "music_queue_empty": "Η ουρά θα εμφανιστεί εδώ μετά την «Ανάλυση Links» — θα δεις εξώφυλλο, "
                              "τίτλο και διάρκεια για κάθε κομμάτι.",
        "music_format_label": "🎚 Μορφή/ποιότητα λήψης (για όλα τα κομμάτια):",
        "music_format_col": "Μορφή",
        "music_bitrate_col": "Bitrate",
        "music_bitrate_best": "Βέλτιστο",
        "music_samplerate_col": "Sample rate",
        "music_samplerate_source": "Όπως η πηγή",
        "music_download_all_btn": "🚀 Λήψη Όλων",
        "music_cancel_btn": "✖ Ακύρωση",
        "music_row_analyzing": "⏳ Ανάλυση...",
        "music_row_pending": "🟠 Αναμονή για λήψη",
        "music_row_queued": "🟠 Στην ουρά λήψης...",
        "music_row_downloading": "⏳ Κατεβαίνει{attempt}...",
        "music_row_done": "✅ Κατέβηκε",
        "music_row_failed": "❌ Απέτυχε: {tail}",
        "music_row_analysis_failed": "⚠ Αποτυχία ανάλυσης",
        "music_preview_btn": "🔊 Preview",
        "music_preview_loading": "⏳ Λήψη δείγματος...",
        "music_play_btn": "▶  Play",
        "music_pause_btn": "⏸  Παύση",
        "music_status_analyzing": "🔎 Ανάλυση links σε εξέλιξη...",
        "music_status_all_ready": "🟠 Όλα σε αναμονή ({ok}) — πάτα «Λήψη Όλων» όποτε θες.",
        "music_status_some_failed": "🟠 Έτοιμα {ok} • ⚠ Απέτυχαν {failed} — αφαίρεσέ τα με ✖ και συνέχισε.",
        "music_status_downloading": "⏳ Λήψη ({i}/{total}){attempt}...",
        "music_status_retry_wait": "⚠ Απέτυχε ({i}/{total}) — αναμονή {wait}s πριν ξαναδοκιμάσουμε...",
        "music_status_cancelled": "⛔ Ακυρώθηκε. Ολοκληρώθηκαν {ok}/{total}.",
        "music_status_all_done": "😎 Όλα έτοιμα! {ok}/{total} κομμάτια κατέβηκαν επιτυχώς. 🎸",
        "music_status_partial_fail": "⚠ Ολοκληρώθηκε: {ok}/{total} επιτυχή.\nΑπέτυχαν:\n{summary}",
        "music_err_no_link": "Δώσε τουλάχιστον ένα link!",
        "music_err_queue_full_title": "Η ουρά είναι γεμάτη",
        "music_err_queue_full": "Η ουρά έχει ήδη {have} τραγούδια και το όριο είναι {max}. "
                                 "Αφαίρεσε κάποιο ή κατέβασέ το πρώτα.",
        "music_err_no_new_links_title": "Δεν βρέθηκαν νέα links",
        "music_err_no_new_links": "Όλα τα links που έδωσες είναι ήδη στην ουρά.",
        "music_err_no_ready": "Δεν υπάρχουν έτοιμα κομμάτια για λήψη.",
        "music_warn_playlist_title": "Playlist Link",
        "music_warn_playlist": "Εντόπισα link που περιέχει playlist (list=...).\n"
                                "Θα κατέβει μόνο το πρώτο κομμάτι της playlist, όχι όλα.",

        # -- Βίντεο --
        "video_header_title": "🎬 Λήψη Βίντεο (MP4)",
        "video_subtitle": "📂 Αποθήκευση σε: {path}",
        "video_link_label": "🔗 Link βίντεο (YouTube, Vimeo, TikTok, Facebook, Instagram κ.ά.) — δεξί κλικ για επικόλληση:",
        "video_analyze_btn": "🔍 Ανάλυση Video",
        "video_analyzing_btn": "⏳ Ανάλυση...",
        "video_placeholder_title": "Δώσε ένα link και πάτα «Ανάλυση Video»",
        "video_preset_label": "Γρήγορη επιλογή:",
        "video_preset_best": "Καλύτερη",
        "video_preset_audio": "🎧 Μόνο Ήχος",
        "video_col_quality": "Ποιότητα",
        "video_col_resolution": "Ανάλυση",
        "video_col_ext": "Μορφή",
        "video_col_fps": "FPS",
        "video_col_size": "Μέγεθος",
        "video_col_video": "Video codec",
        "video_col_audio": "Ήχος",
        "video_audio_only_row": "🎧 Μόνο Ήχος",
        "video_no_audio": "— (χωρίς ήχο)",
        "video_audio_mix_label": "🎧 Ήχος για συνδυασμό με βίντεο-μόνο μορφές:",
        "video_dl_btn": "⬇  Κατέβασμα",
        "video_cancel_btn": "✖ Ακύρωση",
        "video_status_analyzing": "⏳ Ανάλυση link και διαθέσιμων μορφών...",
        "video_status_ready": "🟠 Έλεγχος ολοκληρώθηκε — επίλεξε μορφή και κατέβασε.",
        "video_status_no_formats": "⚠ Δεν βρέθηκαν μορφές βίντεο — μπορείς να κατεβάσεις μόνο ήχο.",
        "video_status_downloading": "⏳ Κατεβαίνει...",
        "video_status_done": "🎬 Έτοιμο το βιντεάκι, πάμε στο επόμενο! 🚀",
        "video_status_cancelled": "⛔ Η λήψη ακυρώθηκε.",
        "video_status_error": "❌ Σφάλμα λήψης:\n{tail}",
        "video_status_error_short": "❌ Σφάλμα λήψης: {err}",
        "video_status_analysis_failed": "❌ {err}",
        "video_open_folder_btn": "📂 Άνοιγμα φακέλου",
        "video_open_file_btn": "▶  Άνοιγμα αρχείου",
        "video_play_here_btn": "▶  Play εδώ",
        "video_err_no_link": "Δώσε ένα έγκυρο link!",
        "video_err_no_analysis": "Κάνε πρώτα «Ανάλυση Video».",
        "video_err_no_format": "Επίλεξε μια μορφή από τη λίστα!",
        "video_err_bad_selection": "Λάθος επιλογή!",

        # -- Ρυθμίσεις --
        "settings_header_title": "⚙️  Ρυθμίσεις",
        "settings_subtitle": "Θέμα, φάκελοι αποθήκευσης και ενημερώσεις",
        "settings_appearance": "Εμφάνιση",
        "settings_theme_current": "Τρέχον θέμα: {theme}",
        "settings_theme_dark": "🌌 Σκοτεινό",
        "settings_theme_light": "🌙 Φωτεινό",
        "settings_theme_switch_to": "🔄 Εναλλαγή σε {theme}",
        "settings_accent": "Χρώμα Εφαρμογής",
        "settings_accent_desc": "Το χρώμα των κουμπιών ενέργειας και των επικεφαλίδων στις οθόνες Μουσικής/Βίντεο.",
        "settings_accent_custom_btn": "🎨 Άλλο χρώμα...",
        "settings_language": "Γλώσσα",
        "settings_language_desc": "Η γλώσσα της εφαρμογής — αποθηκεύεται αυτόματα.",
        "settings_updates": "Ενημερώσεις",
        "settings_ytdlp_engine": "Μηχανή λήψης (yt-dlp)",
        "settings_last_check": "τελευταίος έλεγχος: {date}",
        "settings_never_checked": "δεν έχει ελεγχθεί ποτέ",
        "settings_check_now": "Έλεγχος Τώρα",
        "settings_checking": "⏳ Έλεγχος...",
        "settings_app_version": "Έκδοση Εφαρμογής",
        "settings_check_new_version": "Έλεγχος Νέας Έκδοσης",
        "settings_ytdlp_autoupdate": "🔁 Αυτόματη ενημέρωση yt-dlp κάθε 30 ημέρες (προτείνεται — χωρίς αυτό, "
                                      "οι λήψεις μπορεί να σταματήσουν να δουλεύουν όποτε αλλάζει κάτι στο YouTube)",
        "settings_app_autocheck": "🔔 Αυτόματος έλεγχος για νέα έκδοση εφαρμογής κατά την εκκίνηση",
        "settings_folders": "Φάκελοι Αποθήκευσης",
        "settings_music_folder": "🎵 Φάκελος MP3",
        "settings_video_folder": "🎬 Φάκελος Βίντεο",
        "settings_change_btn": "Αλλαγή",
        "settings_reset": "Επαναφορά",
        "settings_reset_desc": "Επαναφέρει όλες τις ρυθμίσεις (φακέλους, θέμα, χρώμα εφαρμογής, γλώσσα, "
                                "μορφή/ποιότητα ήχου) στις αρχικές τιμές.",
        "settings_reset_btn": "🗑  Επαναφορά Ρυθμίσεων",
        "settings_reset_confirm_title": "Επαναφορά",
        "settings_reset_confirm": "Σίγουρα θέλεις να επαναφέρεις τις ρυθμίσεις στις αρχικές τιμές;",
        "settings_reset_done_title": "Reset",
        "settings_reset_done": "Οι ρυθμίσεις επαναφέρθηκαν επιτυχώς!",
        "settings_footer": "YT & Multi-Source Downloader v{version}",

        # -- Μηνύματα ενημέρωσης / γενικά --
        "msg_ytdlp_up_to_date_title": "yt-dlp",
        "msg_ytdlp_up_to_date": "Έχεις ήδη τη νεότερη έκδοση! ✅",
        "msg_ytdlp_done_title": "yt-dlp",
        "msg_ytdlp_done": "Ολοκληρώθηκε:\n\n{output}",
        "msg_ytdlp_update_error_title": "Σφάλμα Ενημέρωσης",
        "msg_app_check_error_title": "Σφάλμα",
        "msg_app_check_error": "Αποτυχία σύνδεσης στο GitHub για έλεγχο έκδοσης!",
        "msg_app_up_to_date_title": "Έλεγχος Έκδοσης",
        "msg_app_up_to_date": "Έχεις ήδη τη νεότερη έκδοση! (v{version})",
        "msg_update_available_title": "Νέα Έκδοση Διαθέσιμη",
        "msg_update_progress_title": "Ενημέρωση...",
        "msg_update_progress": "⏳ Λήψη νέας έκδοσης, παρακαλώ περιμένετε...",
        "msg_update_error_title": "Σφάλμα Ενημέρωσης",
        "msg_update_found": "Βρέθηκε νέα έκδοση: v{version} (τρέχουσα: v{current})",
        "msg_update_whats_new": "\n\nΤι νέο υπάρχει:\n{notes}",
        "msg_update_protected_folder": "\n\n(Το πρόγραμμα φαίνεται εγκατεστημένο σε προστατευμένο φάκελο — άνοιγμα σελίδας λήψης.)",
        "msg_update_no_auto_link": "\n\n(Δεν βρέθηκε αυτόματο link λήψης — άνοιγμα σελίδας.)",
        "msg_update_confirm_now": "\n\nΝα γίνει η ενημέρωση τώρα; Το πρόγραμμα θα κλείσει και θα ξανανοίξει μόνο του.",
        "msg_ytdlp_auto_updated_title": "yt-dlp Ενημερώθηκε",
        "msg_ytdlp_auto_updated": "Το yt-dlp ενημερώθηκε αυτόματα στη νεότερη έκδοση! 🎉",
        "msg_player_unavailable_title": "Μη διαθέσιμο",
        "msg_player_unavailable": "Η αναπαραγωγή ήχου δεν είναι διαθέσιμη σε αυτόν τον υπολογιστή "
                                   "(δεν βρέθηκε συσκευή ήχου ή λείπει η βιβλιοθήκη pygame).",
        "msg_file_not_found_title": "Σφάλμα",
        "msg_file_not_found": "Το αρχείο δεν βρέθηκε:\n{path}",
        "msg_play_error_title": "Σφάλμα Αναπαραγωγής",
        "msg_preview_error_title": "Σφάλμα Preview",
        "msg_open_error_title": "Σφάλμα",
        "msg_open_error": "Δεν ήταν δυνατό το άνοιγμα:\n{err}",
    },
    "en": {
        "app_title": "YouTube & Multi-Source Downloader",
        "back": "⬅  Back",
        "error_title": "Error",
        "clear_btn": "🧹 Clear",

        "dashboard_title": "🚀 Media Downloader",
        "dashboard_subtitle": "MP3 • MP4 • YouTube, SoundCloud, TikTok, Vimeo & more",
        "dashboard_music_title": "MP3 Songs",
        "dashboard_music_desc": "Download audio as MP3 — up to 5 tracks, with cover preview.",
        "dashboard_video_title": "MP4 Video",
        "dashboard_video_desc": "Download video with resolution/format choice and preview.",
        "dashboard_settings_title": "Settings",
        "dashboard_settings_desc": "Appearance, save folders, updates.",
        "dashboard_exit_title": "Exit",
        "dashboard_exit_desc": "Close the application.",
        "dashboard_footer": "v{version}  •  Made with 🤪 and Python — portable, runs from USB",

        "music_header_title": "🎵 Download Music",
        "music_subtitle": "📂 Saving to: {path}",
        "music_instructions": "Paste one or more links (up to {max} total in the queue) from "
                               "YouTube, SoundCloud, Bandcamp and more — right-click to paste.",
        "music_analyze_btn": "🔎 Analyze Links",
        "music_analyzing_btn": "⏳ Analyzing...",
        "music_reset_btn": "🧹 New List",
        "music_queue_label": "Song queue:",
        "music_queue_empty": "The queue will appear here after «Analyze Links» — you'll see the "
                              "cover, title and duration for each track.",
        "music_format_label": "🎚 Download format/quality (applies to all tracks):",
        "music_format_col": "Format",
        "music_bitrate_col": "Bitrate",
        "music_bitrate_best": "Best",
        "music_samplerate_col": "Sample rate",
        "music_samplerate_source": "Same as source",
        "music_download_all_btn": "🚀 Download All",
        "music_cancel_btn": "✖ Cancel",
        "music_row_analyzing": "⏳ Analyzing...",
        "music_row_pending": "🟠 Waiting to download",
        "music_row_queued": "🟠 Queued for download...",
        "music_row_downloading": "⏳ Downloading{attempt}...",
        "music_row_done": "✅ Downloaded",
        "music_row_failed": "❌ Failed: {tail}",
        "music_row_analysis_failed": "⚠ Analysis failed",
        "music_preview_btn": "🔊 Preview",
        "music_preview_loading": "⏳ Fetching sample...",
        "music_play_btn": "▶  Play",
        "music_pause_btn": "⏸  Pause",
        "music_status_analyzing": "🔎 Analyzing links...",
        "music_status_all_ready": "🟠 All waiting ({ok}) — hit «Download All» whenever you're ready.",
        "music_status_some_failed": "🟠 Ready {ok} • ⚠ Failed {failed} — remove them with ✖ and continue.",
        "music_status_downloading": "⏳ Downloading ({i}/{total}){attempt}...",
        "music_status_retry_wait": "⚠ Failed ({i}/{total}) — waiting {wait}s before retrying...",
        "music_status_cancelled": "⛔ Cancelled. Finished {ok}/{total}.",
        "music_status_all_done": "😎 All done! {ok}/{total} tracks downloaded successfully. 🎸",
        "music_status_partial_fail": "⚠ Finished: {ok}/{total} succeeded.\nFailed:\n{summary}",
        "music_err_no_link": "Give at least one link!",
        "music_err_queue_full_title": "Queue is full",
        "music_err_queue_full": "The queue already has {have} songs and the limit is {max}. "
                                 "Remove one or download it first.",
        "music_err_no_new_links_title": "No new links found",
        "music_err_no_new_links": "All the links you gave are already in the queue.",
        "music_err_no_ready": "There are no ready tracks to download.",
        "music_warn_playlist_title": "Playlist Link",
        "music_warn_playlist": "I found a link that contains a playlist (list=...).\n"
                                "Only the first video of the playlist will be downloaded, not all of it.",

        "video_header_title": "🎬 Download Video (MP4)",
        "video_subtitle": "📂 Saving to: {path}",
        "video_link_label": "🔗 Video link (YouTube, Vimeo, TikTok, Facebook, Instagram & more) — right-click to paste:",
        "video_analyze_btn": "🔍 Analyze Video",
        "video_analyzing_btn": "⏳ Analyzing...",
        "video_placeholder_title": "Give a link and press «Analyze Video»",
        "video_preset_label": "Quick pick:",
        "video_preset_best": "Best",
        "video_preset_audio": "🎧 Audio Only",
        "video_col_quality": "Quality",
        "video_col_resolution": "Resolution",
        "video_col_ext": "Format",
        "video_col_fps": "FPS",
        "video_col_size": "Size",
        "video_col_video": "Video codec",
        "video_col_audio": "Audio",
        "video_audio_only_row": "🎧 Audio Only",
        "video_no_audio": "— (no audio)",
        "video_audio_mix_label": "🎧 Audio to combine with video-only formats:",
        "video_dl_btn": "⬇  Download",
        "video_cancel_btn": "✖ Cancel",
        "video_status_analyzing": "⏳ Analyzing link and available formats...",
        "video_status_ready": "🟠 Check complete — pick a format and download.",
        "video_status_no_formats": "⚠ No video formats found — you can still download audio only.",
        "video_status_downloading": "⏳ Downloading...",
        "video_status_done": "🎬 Your video is ready, on to the next one! 🚀",
        "video_status_cancelled": "⛔ Download cancelled.",
        "video_status_error": "❌ Download error:\n{tail}",
        "video_status_error_short": "❌ Download error: {err}",
        "video_status_analysis_failed": "❌ {err}",
        "video_open_folder_btn": "📂 Open folder",
        "video_open_file_btn": "▶  Open file",
        "video_play_here_btn": "▶  Play here",
        "video_err_no_link": "Give a valid link!",
        "video_err_no_analysis": "Run «Analyze Video» first.",
        "video_err_no_format": "Pick a format from the list!",
        "video_err_bad_selection": "Invalid selection!",

        "settings_header_title": "⚙️  Settings",
        "settings_subtitle": "Theme, save folders and updates",
        "settings_appearance": "Appearance",
        "settings_theme_current": "Current theme: {theme}",
        "settings_theme_dark": "🌌 Dark",
        "settings_theme_light": "🌙 Light",
        "settings_theme_switch_to": "🔄 Switch to {theme}",
        "settings_accent": "App Color",
        "settings_accent_desc": "The color of action buttons and headers on the Music/Video screens.",
        "settings_accent_custom_btn": "🎨 Custom color...",
        "settings_language": "Language",
        "settings_language_desc": "The app's language — saved automatically.",
        "settings_updates": "Updates",
        "settings_ytdlp_engine": "Download engine (yt-dlp)",
        "settings_last_check": "last checked: {date}",
        "settings_never_checked": "never checked",
        "settings_check_now": "Check Now",
        "settings_checking": "⏳ Checking...",
        "settings_app_version": "App Version",
        "settings_check_new_version": "Check for New Version",
        "settings_ytdlp_autoupdate": "🔁 Automatically update yt-dlp every 30 days (recommended — without "
                                      "this, downloads may stop working whenever YouTube changes something)",
        "settings_app_autocheck": "🔔 Automatically check for a new app version on startup",
        "settings_folders": "Save Folders",
        "settings_music_folder": "🎵 MP3 Folder",
        "settings_video_folder": "🎬 Video Folder",
        "settings_change_btn": "Change",
        "settings_reset": "Reset",
        "settings_reset_desc": "Resets all settings (folders, theme, app color, language, "
                                "audio format/quality) to their default values.",
        "settings_reset_btn": "🗑  Reset Settings",
        "settings_reset_confirm_title": "Reset",
        "settings_reset_confirm": "Are you sure you want to reset settings to their default values?",
        "settings_reset_done_title": "Reset",
        "settings_reset_done": "Settings were reset successfully!",
        "settings_footer": "YT & Multi-Source Downloader v{version}",

        "msg_ytdlp_up_to_date_title": "yt-dlp",
        "msg_ytdlp_up_to_date": "You're already on the latest version! ✅",
        "msg_ytdlp_done_title": "yt-dlp",
        "msg_ytdlp_done": "Done:\n\n{output}",
        "msg_ytdlp_update_error_title": "Update Error",
        "msg_app_check_error_title": "Error",
        "msg_app_check_error": "Failed to connect to GitHub to check the version!",
        "msg_app_up_to_date_title": "Version Check",
        "msg_app_up_to_date": "You're already on the latest version! (v{version})",
        "msg_update_available_title": "New Version Available",
        "msg_update_progress_title": "Updating...",
        "msg_update_progress": "⏳ Downloading new version, please wait...",
        "msg_update_error_title": "Update Error",
        "msg_update_found": "Found a new version: v{version} (current: v{current})",
        "msg_update_whats_new": "\n\nWhat's new:\n{notes}",
        "msg_update_protected_folder": "\n\n(The app appears to be installed in a protected folder — opening the download page.)",
        "msg_update_no_auto_link": "\n\n(No automatic download link found — opening the page.)",
        "msg_update_confirm_now": "\n\nUpdate now? The app will close and reopen automatically.",
        "msg_ytdlp_auto_updated_title": "yt-dlp Updated",
        "msg_ytdlp_auto_updated": "yt-dlp was automatically updated to the latest version! 🎉",
        "msg_player_unavailable_title": "Unavailable",
        "msg_player_unavailable": "Audio playback isn't available on this computer "
                                   "(no audio device found, or the pygame library is missing).",
        "msg_file_not_found_title": "Error",
        "msg_file_not_found": "File not found:\n{path}",
        "msg_play_error_title": "Playback Error",
        "msg_preview_error_title": "Preview Error",
        "msg_open_error_title": "Error",
        "msg_open_error": "Could not open:\n{err}",
    },
}


# ======================================================================
#  Κύρια Εφαρμογή
# ======================================================================
class DownloaderApp:
    # Χρώματα ενοτήτων (πλοήγηση — κάρτες dashboard / ενότητες ρυθμίσεων).
    # Παραμένουν σταθερά ώστε να ξεχωρίζουν οι οθόνες μεταξύ τους με μια ματιά.
    ACCENT_MUSIC = "#22c55e"
    ACCENT_VIDEO = "#3b82f6"
    ACCENT_SETTINGS = "#f59e0b"
    ACCENT_DANGER = "#ef4444"

    # «Χρώμα εφαρμογής» — αυτό αλλάζει ο χρήστης από τις Ρυθμίσεις (παλέτα).
    # Χρησιμοποιείται στα header strips των οθονών Μουσικής/Βίντεο και στα κύρια
    # κουμπιά ενέργειας (Ανάλυση/Λήψη/Κατέβασμα), ώστε να αλλάζει ορατά η «ταυτότητα»
    # της εφαρμογής χωρίς να χαλάει τη χρωματική πλοήγηση του dashboard.
    DEFAULT_ACCENT = "#3b82f6"
    ACCENT_PRESETS = [
        ("Μπλε", "#3b82f6"), ("Πράσινο", "#22c55e"), ("Μοβ", "#8b5cf6"),
        ("Ροζ", "#ec4899"), ("Πορτοκαλί", "#f97316"), ("Τιρκουάζ", "#14b8a6"),
    ]

    # Χρώματα κατάστασης λήψης — ΣΤΑΘΕΡΑ, ανεξάρτητα από το accent, ώστε να έχουν
    # πάντα το ίδιο νόημα: πορτοκαλί = αναμονή, μπλε = ενεργή λήψη, πράσινο = έτοιμο,
    # κόκκινο = σφάλμα.
    STATUS_PENDING = "#f59e0b"
    STATUS_ACTIVE = "#3b82f6"
    STATUS_DONE = "#22c55e"
    STATUS_FAILED = "#ef4444"

    DEFAULT_GEOMETRY = "760x680"
    MIN_W, MIN_H = 720, 620

    def __init__(self, root, single_instance_sock=None):
        self.root = root
        self.config = load_config()
        self.root.title(self.tr("app_title"))
        self.root.minsize(self.MIN_W, self.MIN_H)
        self._single_instance_sock = single_instance_sock
        if single_instance_sock is not None:
            self._start_single_instance_listener(single_instance_sock)

        self._restore_geometry()
        self._geometry_save_job = None
        self.player = AudioPlayer()
        self.player.on_state_change = self._on_player_state_change
        self._active_play_button = None  # το κουμπί play/pause που αντιστοιχεί στο τρέχον track

        self._apply_icon(self.root)

        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.container = tk.Frame(self.root)
        self.container.pack(fill="both", expand=True)

        self.current_process = None
        self.cancel_requested = False

        # Ουρά τραγουδιών (οθόνη μουσικής) — λίστα από dicts, βλέπε build_music_screen
        self.music_queue = []
        # Δεδομένα μορφών βίντεο (id -> format dict) της τρέχουσας ανάλυσης
        self.video_formats_by_iid = {}
        self.video_meta = None

        clear_preview_cache()
        self.apply_ttk_styles()
        self.show_dashboard()
        self.root.after(1500, self.maybe_auto_update_ytdlp)
        self.root.after(2000, self.check_app_update_silent)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Αποθήκευση θέσης/μεγέθους παραθύρου (με μικρή καθυστέρηση ώστε να μη γράφουμε
        # στο δίσκο σε κάθε pixel ενώ σέρνεις/αλλάζεις μέγεθος — μόνο όταν σταματήσεις).
        self.root.bind("<Configure>", self._on_window_configure)

    # ------------------------------------------------------------------
    #  Μία μόνο διεργασία — αν ήδη τρέχει η εφαρμογή, το εικονίδιο απλά τη φέρνει
    #  μπροστά αντί να ανοίγει δεύτερο παράθυρο (βλ. acquire_single_instance_lock).
    # ------------------------------------------------------------------
    def _start_single_instance_listener(self, sock):
        def accept_loop():
            while True:
                try:
                    conn, _addr = sock.accept()
                except OSError:
                    break
                try:
                    conn.settimeout(1.0)
                    conn.recv(16)
                except Exception:
                    pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
                try:
                    self.root.after(0, self._bring_window_to_front)
                except Exception:
                    break
        threading.Thread(target=accept_loop, daemon=True).start()

    def _bring_window_to_front(self):
        try:
            if self.root.state() == "iconic":
                self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(250, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _restore_geometry(self):
        geo = (self.config.get("window_geometry") or "").strip()
        ok = False
        if geo:
            m = re.match(r'^(\d+)x(\d+)([+-]\d+)([+-]\d+)$', geo)
            if m:
                w, h, x, y = (int(v) for v in m.groups())
                try:
                    screen_w = self.root.winfo_screenwidth()
                    screen_h = self.root.winfo_screenheight()
                except Exception:
                    screen_w, screen_h = 1920, 1080
                w = max(w, self.MIN_W)
                h = max(h, self.MIN_H)
                # Λογικά όρια ώστε το παράθυρο να μη "χαθεί" εκτός οθόνης
                # (π.χ. αν άλλαξε ανάλυση/αριθμός οθονών από την τελευταία φορά).
                if -50 <= x <= screen_w - 100 and -50 <= y <= screen_h - 100:
                    self.root.geometry(f"{w}x{h}+{x}+{y}")
                    ok = True
        if not ok:
            self.root.geometry(self.DEFAULT_GEOMETRY)

    def _on_window_configure(self, event):
        if event.widget is not self.root:
            return
        if self._geometry_save_job:
            self.root.after_cancel(self._geometry_save_job)
        self._geometry_save_job = self.root.after(700, self._save_geometry_now)

    def _save_geometry_now(self):
        self._geometry_save_job = None
        try:
            geo = self.root.geometry()  # "WxH+X+Y"
            if re.match(r'^\d+x\d+[+-]\d+[+-]\d+$', geo):
                if geo != self.config.get("window_geometry"):
                    self.config["window_geometry"] = geo
                    save_config(self.config)
        except Exception:
            pass

    def _on_close(self):
        try:
            self.player.stop()
        except Exception:
            pass
        try:
            self._save_geometry_now()
        except Exception:
            pass
        if self._single_instance_sock is not None:
            try:
                self._single_instance_sock.close()
            except Exception:
                pass
        clear_preview_cache()
        self.root.destroy()

    def _apply_icon(self, window):
        try:
            icon_path = get_resource_path("icon.ico")
            if os.path.exists(icon_path):
                window.iconbitmap(icon_path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  Γλώσσα
    # ------------------------------------------------------------------
    @property
    def lang(self):
        return "en" if self.config.get("language") == "en" else "el"

    def tr(self, key, **kwargs):
        table = TRANSLATIONS.get(self.lang) or TRANSLATIONS["el"]
        text = table.get(key)
        if text is None:
            text = TRANSLATIONS["el"].get(key, key)
        if kwargs:
            try:
                return text.format(**kwargs)
            except Exception:
                return text
        return text

    # ------------------------------------------------------------------
    #  Θέμα / χρώματα
    # ------------------------------------------------------------------
    @property
    def accent(self):
        return self.config.get("accent_color") or self.DEFAULT_ACCENT

    @property
    def c(self):
        if self.config.get("theme") == "light":
            return {
                "bg": "#f5f6fa", "fg": "#1f2430", "muted": "#6b7280",
                "card_bg": "#ffffff", "card_border": "#e2e5ec",
                "header_bg": "#ffffff", "input_bg": "#ffffff", "input_fg": "#1f2430",
                "input_border": "#d7dbe3", "btn_bg": "#eef0f4", "btn_fg": "#1f2430",
                "btn_hover": "#e2e5ec", "track_bg": "#eceef3",
            }
        return {
            "bg": "#0f1115", "fg": "#eef0f4", "muted": "#8b93a3",
            "card_bg": "#171a21", "card_border": "#262b36",
            "header_bg": "#12141a", "input_bg": "#1d2129", "input_fg": "#eef0f4",
            "input_border": "#2c313d", "btn_bg": "#1d2129", "btn_fg": "#eef0f4",
            "btn_hover": "#262b36", "track_bg": "#20242c",
        }

    def apply_ttk_styles(self):
        c = self.c
        s = self.style
        s.configure("TCombobox", fieldbackground=c["input_bg"], background=c["input_bg"],
                    foreground=c["input_fg"], arrowcolor=c["fg"])
        s.map("TCombobox", fieldbackground=[("readonly", c["input_bg"])],
              foreground=[("readonly", c["input_fg"])])
        s.configure("TScrollbar", background=c["btn_bg"], troughcolor=c["bg"],
                    bordercolor=c["bg"], arrowcolor=c["fg"])
        s.configure("Horizontal.TProgressbar", background=self.ACCENT_MUSIC,
                    troughcolor=c["track_bg"], bordercolor=c["track_bg"],
                    lightcolor=self.ACCENT_MUSIC, darkcolor=self.ACCENT_MUSIC)
        s.configure("Treeview", background=c["card_bg"], fieldbackground=c["card_bg"],
                    foreground=c["fg"], rowheight=26, bordercolor=c["card_border"],
                    borderwidth=0)
        s.configure("Treeview.Heading", background=c["header_bg"], foreground=c["fg"],
                    relief="flat")
        s.map("Treeview", background=[("selected", self.ACCENT_VIDEO)],
              foreground=[("selected", "#ffffff")])
        s.configure("TSeparator", background=c["card_border"])

    def apply_window_theme(self):
        self.root.configure(bg=self.c["bg"])
        self.container.configure(bg=self.c["bg"])
        self.apply_ttk_styles()

    def clear_container(self):
        self.music_queue = []
        for widget in self.container.winfo_children():
            widget.destroy()
        self.apply_window_theme()

    def font(self, size=10, weight="normal", italic=False):
        if italic:
            return (FONT_FAMILY, size, weight, "italic")
        return (FONT_FAMILY, size, weight)

    # ------------------------------------------------------------------
    #  Κοινό header (τίτλος οθόνης + πίσω) — αντικαθιστά τα εύθραυστα .place()
    # ------------------------------------------------------------------
    def build_header(self, title, subtitle=None, accent=None, on_back=None):
        c = self.c
        accent = accent or self.accent
        header = tk.Frame(self.container, bg=c["header_bg"])
        header.pack(fill="x", side="top")

        inner = tk.Frame(header, bg=c["header_bg"])
        inner.pack(fill="x", padx=16, pady=(12, 12))

        if on_back:
            back_btn = tk.Button(inner, text=self.tr("back"), font=self.font(9, "bold"),
                                  bg=c["btn_bg"], fg=c["fg"], activebackground=c["btn_hover"],
                                  bd=0, padx=10, pady=6, cursor="hand2", command=on_back)
            back_btn.pack(side="left", padx=(0, 12))
            bind_hover(back_btn, c["btn_bg"], c["btn_hover"])

        text_col = tk.Frame(inner, bg=c["header_bg"])
        text_col.pack(side="left", fill="x", expand=True)

        title_row = tk.Frame(text_col, bg=c["header_bg"])
        title_row.pack(fill="x")
        tk.Frame(title_row, bg=accent, width=4, height=22).pack(side="left", padx=(0, 8))
        tk.Label(title_row, text=title, font=self.font(15, "bold"), fg=c["fg"],
                 bg=c["header_bg"]).pack(side="left", anchor="w")

        if subtitle:
            tk.Label(text_col, text=subtitle, font=self.font(9), fg=c["muted"],
                     bg=c["header_bg"], justify="left", anchor="w").pack(fill="x", padx=(12, 0))

        ttk.Separator(self.container, orient="horizontal").pack(fill="x")
        return header

    # ------------------------------------------------------------------
    def stop_current_download(self):
        self.cancel_requested = True
        if self.current_process and self.current_process.poll() is None:
            try:
                self.current_process.terminate()
            except Exception:
                pass

    def _on_player_state_change(self, path, playing):
        btn = self._active_play_button
        if btn is None:
            return
        try:
            if not btn.winfo_exists():
                self._active_play_button = None
                return
        except Exception:
            self._active_play_button = None
            return
        target_path = getattr(btn, "_track_path", None)
        if target_path and path and os.path.abspath(target_path) == os.path.abspath(path):
            self._set_play_button_state(btn, playing)
        else:
            self._set_play_button_state(btn, False)

    def _set_play_button_state(self, btn, playing):
        """ Play=μπλε (STATUS_ACTIVE), Pause=πορτοκαλί (STATUS_PENDING) — έτσι το χρώμα
        του κουμπιού δείχνει πάντα τι θα κάνει το επόμενο κλικ. """
        new_color = self.STATUS_PENDING if playing else self.STATUS_ACTIVE
        if playing:
            btn.configure(text=self.tr("music_pause_btn"), bg=new_color, activebackground=new_color)
        else:
            btn.configure(text=self.tr("music_play_btn"), bg=new_color, activebackground=new_color)
        # ΣΗΜΑΝΤΙΚΟ: ενημερώνουμε το «χρώμα ηρεμίας» που χρησιμοποιεί το
        # bind_hover_dynamic ΑΜΕΣΩΣ εδώ (όχι μόνο στο επόμενο <Enter>) — αλλιώς, αν το
        # κλικ που άλλαξε την κατάσταση έγινε ενώ το ποντίκι ήταν ήδη πάνω στο κουμπί
        # (το σύνηθες σενάριο: κλικάρεις κάτι που το ποντίκι είναι ήδη πάνω του), το
        # <Leave> θα γύριζε το κουμπί στο ΠΑΛΙΟ χρώμα αντί για το νέο.
        btn._rest_bg = new_color
        # Σε μερικά Windows, ένα tk.Button δεν ξαναζωγραφίζει αμέσως το φόντο του μετά
        # από configure() -- φαίνεται σωστά μόνο όταν το ποντίκι περάσει από πάνω (που
        # προκαλεί ξαναζωγράφισμα). Το update_idletasks() εδώ αναγκάζει άμεσο repaint.
        try:
            btn.update_idletasks()
        except Exception:
            pass

    def play_local_file(self, path, button):
        """ Play/Pause toggle ενός τοπικού αρχείου, δεμένο σε συγκεκριμένο κουμπί. """
        if not PYGAME_AVAILABLE or not self.player.available:
            messagebox.showinfo(self.tr("msg_player_unavailable_title"), self.tr("msg_player_unavailable"))
            return
        if not os.path.exists(path):
            messagebox.showerror(self.tr("msg_file_not_found_title"), self.tr("msg_file_not_found", path=path))
            return

        already_this = (self.player.current_path and
                         os.path.abspath(self.player.current_path) == os.path.abspath(path))
        if already_this and self.player.is_playing():
            self.player.toggle_pause()
            self._active_play_button = button
            return
        if already_this and self.player.paused:
            self.player.toggle_pause()
            self._active_play_button = button
            return

        ok, err = self.player.play(path)
        if not ok:
            messagebox.showerror(self.tr("msg_play_error_title"), err)
            return
        button._track_path = path
        self._active_play_button = button
        self._set_play_button_state(button, True)

    def _open_path(self, path):
        ok, err = open_path_with_default_app(path)
        if not ok:
            messagebox.showerror(self.tr("msg_open_error_title"), self.tr("msg_open_error", err=err))

    # ------------------------------------------------------------------
    #  1. ΚΕΝΤΡΙΚΟ ΜΕΝΟΥ
    # ------------------------------------------------------------------
    def show_dashboard(self):
        self.clear_container()
        c = self.c
        self.player.stop()

        header = tk.Frame(self.container, bg=c["header_bg"])
        header.pack(fill="x")
        inner = tk.Frame(header, bg=c["header_bg"])
        inner.pack(pady=(28, 18))
        tk.Label(inner, text=self.tr("dashboard_title"), font=self.font(22, "bold"),
                 fg=c["fg"], bg=c["header_bg"]).pack()
        tk.Label(inner, text=self.tr("dashboard_subtitle"),
                 font=self.font(10), fg=c["muted"], bg=c["header_bg"]).pack(pady=(4, 0))
        ttk.Separator(self.container, orient="horizontal").pack(fill="x")

        body = tk.Frame(self.container, bg=c["bg"])
        body.pack(fill="both", expand=True, padx=28, pady=22)

        cards = tk.Frame(body, bg=c["bg"])
        cards.pack(fill="both", expand=True)
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)

        self._make_nav_card(cards, "🎵", self.tr("dashboard_music_title"), self.tr("dashboard_music_desc"),
                             self.ACCENT_MUSIC, self.show_music_screen).grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=10)
        self._make_nav_card(cards, "🎬", self.tr("dashboard_video_title"), self.tr("dashboard_video_desc"),
                             self.ACCENT_VIDEO, self.show_video_screen).grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)
        self._make_nav_card(cards, "⚙️", self.tr("dashboard_settings_title"), self.tr("dashboard_settings_desc"),
                             self.ACCENT_SETTINGS, self.show_settings_screen).grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=10)
        self._make_nav_card(cards, "❌", self.tr("dashboard_exit_title"), self.tr("dashboard_exit_desc"),
                             self.ACCENT_DANGER, self._on_close).grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=10)

        footer = tk.Label(self.container, text=self.tr("dashboard_footer", version=APP_VERSION),
                           font=self.font(8), fg=c["muted"], bg=c["bg"])
        footer.pack(side="bottom", pady=10)

    def _make_nav_card(self, parent, icon, title, desc, accent, command):
        c = self.c
        card = tk.Frame(parent, bg=c["card_bg"], highlightthickness=1,
                         highlightbackground=c["card_border"], highlightcolor=c["card_border"],
                         cursor="hand2")
        stripe = tk.Frame(card, bg=accent, height=4)
        stripe.pack(fill="x", side="top")
        pad = tk.Frame(card, bg=c["card_bg"])
        pad.pack(fill="both", expand=True, padx=18, pady=16)
        tk.Label(pad, text=icon, font=self.font(26), bg=c["card_bg"], fg=accent).pack(anchor="w")
        tk.Label(pad, text=title, font=self.font(13, "bold"), bg=c["card_bg"], fg=c["fg"]).pack(anchor="w", pady=(6, 2))
        tk.Label(pad, text=desc, font=self.font(9), bg=c["card_bg"], fg=c["muted"],
                 wraplength=260, justify="left").pack(anchor="w")

        widgets = [card, stripe, pad] + list(pad.winfo_children())

        def on_enter(_e=None):
            card.configure(highlightbackground=accent, highlightcolor=accent)

        def on_leave(_e=None):
            card.configure(highlightbackground=c["card_border"], highlightcolor=c["card_border"])

        for w in widgets:
            w.bind("<Button-1>", lambda _e: command())
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
        return card

    # ------------------------------------------------------------------
    #  2. ΟΘΟΝΗ ΜΟΥΣΙΚΗΣ — ουρά με προεπισκόπηση τίτλου/εξωφύλλου
    # ------------------------------------------------------------------
    AUDIO_FORMATS = [
        ("mp3", "MP3"),
        ("m4a", "M4A (AAC)"),
        ("wav", "WAV"),
        ("flac", "FLAC"),
        ("vorbis", "OGG (Vorbis)"),
    ]
    AUDIO_BITRATES = ["best", "128", "192", "256", "320"]
    AUDIO_SAMPLERATES = ["", "44100", "48000"]

    def show_music_screen(self):
        self.clear_container()
        self.cancel_requested = False
        c = self.c
        self.player.stop()

        self.build_header(self.tr("music_header_title"),
                           subtitle=self.tr("music_subtitle", path=self.config['music_path']),
                           accent=self.accent, on_back=self.show_dashboard)

        outer = ScrollableFrame(self.container, bg=c["bg"], fill_parent=True)
        outer.pack(fill="both", expand=True, padx=18, pady=(12, 10))
        body = outer.body

        tk.Label(body, text=self.tr("music_instructions", max=MAX_BATCH_LINKS),
                 font=self.font(9), fg=c["muted"], bg=c["bg"], wraplength=680, justify="left").pack(anchor="w")

        self.links_text = tk.Text(body, font=self.font(10), height=4, bg=c["input_bg"], fg=c["input_fg"],
                                   insertbackground=c["input_fg"], relief="flat", highlightthickness=1,
                                   highlightbackground=c["input_border"], highlightcolor=self.accent,
                                   padx=8, pady=6)
        self.links_text.pack(fill="x", pady=(6, 8))
        self.links_text.focus()
        add_right_click_paste(self.links_text)

        actions_row = tk.Frame(body, bg=c["bg"])
        actions_row.pack(fill="x")
        self.analyze_btn = self._styled_button(actions_row, self.tr("music_analyze_btn"), self.accent,
                                                 command=self.start_music_analysis)
        self.analyze_btn.pack(side="left")
        self.reset_queue_btn = self._styled_button(actions_row, self.tr("music_reset_btn"), c["btn_bg"], fg=c["fg"],
                                                      command=self.reset_music_queue)
        self.reset_queue_btn.pack(side="left", padx=(8, 0))

        # -- Καθολικές επιλογές μορφής / bitrate / sample rate (ισχύουν για όλη την ουρά) --
        fmt_card = tk.Frame(body, bg=c["card_bg"], highlightthickness=1, highlightbackground=c["card_border"])
        fmt_card.pack(fill="x", pady=(12, 0))
        fmt_inner = tk.Frame(fmt_card, bg=c["card_bg"])
        fmt_inner.pack(fill="x", padx=12, pady=8)
        tk.Label(fmt_inner, text=self.tr("music_format_label"), font=self.font(9, "bold"),
                 fg=c["fg"], bg=c["card_bg"]).pack(anchor="w", pady=(0, 6))

        opts_row = tk.Frame(fmt_inner, bg=c["card_bg"])
        opts_row.pack(fill="x")

        fmt_labels = [label for _key, label in self.AUDIO_FORMATS]
        fmt_keys = [key for key, _label in self.AUDIO_FORMATS]
        current_fmt = self.config.get("audio_format", "mp3")
        self.audio_format_var = tk.StringVar(
            value=fmt_labels[fmt_keys.index(current_fmt)] if current_fmt in fmt_keys else fmt_labels[0])
        tk.Label(opts_row, text=self.tr("music_format_col") + ":", font=self.font(8), fg=c["muted"],
                 bg=c["card_bg"]).pack(side="left", padx=(0, 4))
        format_combo = ttk.Combobox(opts_row, textvariable=self.audio_format_var, values=fmt_labels,
                                     state="readonly", width=14)
        format_combo.pack(side="left", padx=(0, 14))

        bitrate_display = {"best": self.tr("music_bitrate_best")}
        bitrate_values = [bitrate_display.get(b, f"{b} kbps") for b in self.AUDIO_BITRATES]
        current_bitrate = self.config.get("audio_bitrate", "0")
        current_bitrate = "best" if current_bitrate in ("0", "", "best") else current_bitrate
        self.audio_bitrate_var = tk.StringVar(
            value=bitrate_display.get(current_bitrate, f"{current_bitrate} kbps")
            if current_bitrate in self.AUDIO_BITRATES else bitrate_values[0])
        tk.Label(opts_row, text=self.tr("music_bitrate_col") + ":", font=self.font(8), fg=c["muted"],
                 bg=c["card_bg"]).pack(side="left", padx=(0, 4))
        self.bitrate_combo = ttk.Combobox(opts_row, textvariable=self.audio_bitrate_var, values=bitrate_values,
                                           state="readonly", width=10)
        self.bitrate_combo.pack(side="left", padx=(0, 14))

        sr_display = {"": self.tr("music_samplerate_source")}
        sr_values = [sr_display.get(sr, f"{sr} Hz") for sr in self.AUDIO_SAMPLERATES]
        current_sr = self.config.get("audio_samplerate", "")
        self.audio_samplerate_var = tk.StringVar(
            value=sr_display.get(current_sr, f"{current_sr} Hz") if current_sr in self.AUDIO_SAMPLERATES else sr_values[0])
        tk.Label(opts_row, text=self.tr("music_samplerate_col") + ":", font=self.font(8), fg=c["muted"],
                 bg=c["card_bg"]).pack(side="left", padx=(0, 4))
        sr_combo = ttk.Combobox(opts_row, textvariable=self.audio_samplerate_var, values=sr_values,
                                 state="readonly", width=14)
        sr_combo.pack(side="left")

        def on_format_change(_e=None):
            key = fmt_keys[fmt_labels.index(self.audio_format_var.get())]
            self.config["audio_format"] = key
            save_config(self.config)
            # Το bitrate δεν έχει νόημα σε lossless μορφές (WAV/FLAC)
            lossless = key in ("wav", "flac")
            self.bitrate_combo.config(state="disabled" if lossless else "readonly")

        def on_bitrate_change(_e=None):
            val = self.audio_bitrate_var.get()
            key = "0" if val == self.tr("music_bitrate_best") else val.split(" ")[0]
            self.config["audio_bitrate"] = key
            save_config(self.config)

        def on_sr_change(_e=None):
            val = self.audio_samplerate_var.get()
            key = "" if val == self.tr("music_samplerate_source") else val.split(" ")[0]
            self.config["audio_samplerate"] = key
            save_config(self.config)

        format_combo.bind("<<ComboboxSelected>>", on_format_change)
        self.bitrate_combo.bind("<<ComboboxSelected>>", on_bitrate_change)
        sr_combo.bind("<<ComboboxSelected>>", on_sr_change)
        on_format_change()

        tk.Label(body, text=self.tr("music_queue_label"), font=self.font(10, "bold"), fg=c["fg"], bg=c["bg"]).pack(
            anchor="w", pady=(14, 4))

        self.queue_frame = tk.Frame(body, bg=c["bg"])
        self.queue_frame.pack(fill="x")
        self._music_empty_label = tk.Label(self.queue_frame, bg=c["bg"], fg=c["muted"],
                                            font=self.font(9, italic=True),
                                            text=self.tr("music_queue_empty"),
                                            wraplength=660, justify="left")
        self._music_empty_label.pack(anchor="w", pady=8, padx=4)

        status_area = tk.Frame(body, bg=c["bg"])
        status_area.pack(fill="x", pady=(10, 0))
        self.music_status_lbl = tk.Label(status_area, text="", font=self.font(10, "bold"), bg=c["bg"],
                                          fg=c["fg"], wraplength=680, justify="left")
        self.music_status_lbl.pack(anchor="w")
        self.music_progress = GradientProgressBar(status_area, width=450, height=16, bg=c["bg"],
                                                    trough=c["track_bg"], accent=self.STATUS_DONE)
        self.music_progress.pack(fill="x", pady=(6, 2))
        self.music_speed_lbl = tk.Label(status_area, text="", font=self.font(9, italic=True), fg=self.STATUS_ACTIVE,
                                         bg=c["bg"])
        self.music_speed_lbl.pack(anchor="w")

        btn_row = tk.Frame(body, bg=c["bg"])
        btn_row.pack(pady=(10, 0))
        self.download_all_btn = self._styled_button(btn_row, self.tr("music_download_all_btn"), self.STATUS_DONE,
                                                       command=self.start_music_download)
        self.download_all_btn.grid(row=0, column=0, padx=5)
        self.download_all_btn.config(state="disabled")
        self.music_cancel_btn = self._styled_button(btn_row, self.tr("music_cancel_btn"), self.ACCENT_DANGER,
                                                       command=self.cancel_music_download)
        self.music_cancel_btn.grid(row=0, column=1, padx=5)
        self.music_cancel_btn.config(state="disabled")

        self._refresh_music_status()

    def _styled_button(self, parent, text, accent, fg="white", command=None, width=None):
        btn = tk.Button(parent, text=text, font=self.font(10, "bold"), bg=accent, fg=fg,
                         activebackground=accent, activeforeground=fg, bd=0, padx=14, pady=8,
                         cursor="hand2", command=command)
        if width:
            btn.config(width=width)
        hover = self._shade(accent, 0.85) if accent not in (self.c["btn_bg"],) else self.c["btn_hover"]
        bind_hover(btn, accent, hover)
        return btn

    @staticmethod
    def _shade(hex_color, factor):
        try:
            hex_color = hex_color.lstrip("#")
            r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
            r, g, b = (max(0, min(255, int(v * factor))) for v in (r, g, b))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def _clear_frame(self, frame):
        for w in frame.winfo_children():
            w.destroy()

    def reset_music_queue(self):
        self.player.stop()
        self.music_queue = []
        self._clear_frame(self.queue_frame)
        self._music_empty_label = tk.Label(
            self.queue_frame, bg=self.c["bg"], fg=self.c["muted"], font=self.font(9, italic=True),
            text=self.tr("music_queue_empty"), wraplength=660, justify="left")
        self._music_empty_label.pack(anchor="w", pady=8, padx=4)
        self.links_text.delete("1.0", tk.END)
        self.analyze_btn.config(state="normal")
        self.download_all_btn.config(state="disabled")
        self.music_status_lbl.config(text="")
        self.music_progress.set(0)
        self.music_speed_lbl.config(text="")

    # -- Ανάλυση links (τίτλος/εξώφυλλο) πριν το κατέβασμα -------------
    # ΣΗΜΕΙΩΣΗ: το πλαίσιο κειμένου ΔΕΝ κλειδώνεται ποτέ πια — μπορείς να προσθέσεις κι
    # άλλο τραγούδι στην ουρά οποιαδήποτε στιγμή, χωρίς να χρειάζεται «Νέα Λίστα».
    def start_music_analysis(self):
        raw_text = self.links_text.get("1.0", tk.END)
        raw_links = extract_links(raw_text)
        if not raw_links:
            messagebox.showerror(self.tr("error_title"), self.tr("music_err_no_link"))
            return

        existing_links = {it["link"] for it in self.music_queue}
        cleaned = []
        seen = set()
        for l in raw_links:
            link = clean_link(l)
            if link in existing_links or link in seen:
                continue
            seen.add(link)
            cleaned.append(link)

        if not cleaned:
            messagebox.showinfo(self.tr("music_err_no_new_links_title"), self.tr("music_err_no_new_links"))
            return

        available_slots = MAX_BATCH_LINKS - len(self.music_queue)
        if len(cleaned) > available_slots:
            messagebox.showerror(
                self.tr("music_err_queue_full_title"),
                self.tr("music_err_queue_full", have=len(self.music_queue), max=MAX_BATCH_LINKS))
            return

        ytdlp_path = get_bin_path("yt-dlp.exe")
        ok, err_msg = check_tool_available(ytdlp_path, "yt-dlp.exe")
        if not ok:
            messagebox.showerror(self.tr("error_title"), err_msg)
            return

        self.analyze_btn.config(state="disabled", text=self.tr("music_analyzing_btn"))
        self.links_text.delete("1.0", tk.END)  # έτοιμο να δεχτεί την επόμενη παρτίδα links

        new_items = []
        for link in cleaned:
            item = {"link": link, "status": "analyzing", "title": None, "thumbnail_url": None,
                    "pil_thumb": None, "duration": None, "uploader": None, "error": None,
                    "downloaded_path": None, "preview_path": None, "widgets": {}}
            self.music_queue.append(item)
            new_items.append(item)
            self._build_music_row(item)
        self._refresh_music_status()

        def worker():
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
                futures = {ex.submit(self._analyze_one, ytdlp_path, it): it for it in new_items}
                for fut in concurrent.futures.as_completed(futures):
                    it = futures[fut]
                    self.root.after(0, lambda it=it: self._update_music_row(it))
            self.root.after(0, self._after_music_analysis)

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _analyze_one(ytdlp_path, item):
        try:
            meta = fetch_metadata(ytdlp_path, item["link"])
            item["status"] = "ready"
            item["title"] = meta["title"]
            item["thumbnail_url"] = meta["thumbnail"]
            item["duration"] = meta["duration"]
            item["uploader"] = meta["uploader"]
            item["pil_thumb"] = download_thumbnail_pil(meta["thumbnail"])
        except Exception as e:
            item["status"] = "error"
            item["error"] = str(e)
        return item

    def _after_music_analysis(self):
        if not self.analyze_btn.winfo_exists():
            return
        self.analyze_btn.config(state="normal", text=self.tr("music_analyze_btn"))
        self._refresh_music_status()

    def _refresh_music_status(self):
        any_ready = any(it["status"] == "ready" for it in self.music_queue)
        self.download_all_btn.config(state="normal" if any_ready else "disabled")
        if any(it["status"] == "analyzing" for it in self.music_queue):
            self.music_status_lbl.config(text=self.tr("music_status_analyzing"), fg=self.STATUS_ACTIVE)
            return
        failed = sum(1 for it in self.music_queue if it["status"] == "error")
        ok = sum(1 for it in self.music_queue if it["status"] == "ready")
        if not self.music_queue:
            self.music_status_lbl.config(text="")
        elif failed:
            self.music_status_lbl.config(text=self.tr("music_status_some_failed", ok=ok, failed=failed),
                                          fg=self.STATUS_PENDING)
        elif ok:
            self.music_status_lbl.config(text=self.tr("music_status_all_ready", ok=ok), fg=self.STATUS_PENDING)

    def _build_music_row(self, item):
        c = self.c
        if self._music_empty_label and self._music_empty_label.winfo_exists():
            self._music_empty_label.destroy()

        card = tk.Frame(self.queue_frame, bg=c["card_bg"], highlightthickness=1,
                         highlightbackground=c["card_border"])
        card.pack(fill="x", pady=4, padx=2)
        inner = tk.Frame(card, bg=c["card_bg"])
        inner.pack(fill="x", padx=10, pady=8)

        thumb_holder = tk.Frame(inner, bg=c["track_bg"], width=52, height=52)
        thumb_holder.pack(side="left")
        thumb_holder.pack_propagate(False)
        platform_name, platform_icon = guess_platform(item["link"])
        thumb_lbl = tk.Label(thumb_holder, text=platform_icon, font=self.font(20), bg=c["track_bg"], fg=c["fg"])
        thumb_lbl.pack(fill="both", expand=True)

        text_col = tk.Frame(inner, bg=c["card_bg"])
        text_col.pack(side="left", fill="x", expand=True, padx=(10, 6))
        title_lbl = tk.Label(text_col, text=self.tr("music_row_analyzing"), font=self.font(10, "bold"), fg=c["fg"],
                              bg=c["card_bg"], anchor="w", justify="left", wraplength=340)
        title_lbl.pack(fill="x", anchor="w")
        meta_lbl = tk.Label(text_col, text=platform_name, font=self.font(8), fg=c["muted"],
                             bg=c["card_bg"], anchor="w")
        meta_lbl.pack(fill="x", anchor="w")
        status_lbl = tk.Label(text_col, text="", font=self.font(8, "bold"), fg=c["muted"],
                               bg=c["card_bg"], anchor="w")
        status_lbl.pack(fill="x", anchor="w")

        btn_col = tk.Frame(inner, bg=c["card_bg"])
        btn_col.pack(side="right")
        preview_btn = tk.Button(btn_col, text=self.tr("music_preview_btn"), font=self.font(8, "bold"),
                                 bg=c["btn_bg"], fg=c["fg"], bd=0, padx=8, pady=4, cursor="hand2", state="disabled",
                                 command=lambda it=item: self._on_preview_click(it))
        preview_btn.pack(side="left", padx=3)
        # dynamic (όχι bind_hover): αυτό το κουμπί γίνεται Play/Pause με δικό του χρώμα
        # μόλις ξεκινήσει η αναπαραγωγή -- βλ. play_local_file / _set_play_button_state.
        bind_hover_dynamic(preview_btn)
        remove_btn = tk.Button(btn_col, text="✖", font=self.font(9, "bold"), bg=c["btn_bg"], fg=self.ACCENT_DANGER,
                                bd=0, padx=8, pady=4, cursor="hand2",
                                command=lambda it=item: self._remove_music_item(it))
        remove_btn.pack(side="left", padx=3)
        bind_hover(remove_btn, c["btn_bg"], c["btn_hover"])

        item["widgets"] = {"card": card, "thumb_lbl": thumb_lbl, "title_lbl": title_lbl, "meta_lbl": meta_lbl,
                            "status_lbl": status_lbl, "preview_btn": preview_btn, "remove_btn": remove_btn,
                            "btn_col": btn_col, "play_btn": None}

    def _update_music_row(self, item):
        w = item["widgets"]
        if not w or not w["card"].winfo_exists():
            return
        c = self.c
        platform_name, _icon = guess_platform(item["link"])
        if item["status"] == "ready":
            photo = pil_to_photo(item.get("pil_thumb"))
            if photo:
                w["thumb_lbl"].configure(image=photo, text="")
                w["thumb_lbl"].image = photo  # κρατάμε reference, αλλιώς το GC το σβήνει
            title = item["title"] or item["link"]
            w["title_lbl"].configure(text=(title[:60] + "…") if len(title) > 60 else title, fg=c["fg"])
            meta_bits = [platform_name]
            if item.get("uploader"):
                meta_bits.append(item["uploader"])
            meta_bits.append(human_duration(item.get("duration")))
            w["meta_lbl"].configure(text=" • ".join(meta_bits))
            w["status_lbl"].configure(text=self.tr("music_row_pending"), fg=self.STATUS_PENDING)
            w["preview_btn"].configure(state="normal")
        else:
            w["title_lbl"].configure(text=self.tr("music_row_analysis_failed"), fg=self.STATUS_FAILED)
            w["meta_lbl"].configure(text=platform_name)
            err = item.get("error") or "—"
            w["status_lbl"].configure(text=(err[:70] + "…") if len(err) > 70 else err, fg=self.STATUS_FAILED)
        self._refresh_music_status()

    def _remove_music_item(self, item):
        if item["status"] in ("downloading",):
            return
        if self.player.current_path and item.get("downloaded_path") and \
                os.path.abspath(self.player.current_path) == os.path.abspath(item["downloaded_path"]):
            self.player.stop()
        if self.player.current_path and item.get("preview_path") and \
                os.path.abspath(self.player.current_path) == os.path.abspath(item["preview_path"]):
            self.player.stop()
        w = item["widgets"]
        if w and w.get("card") and w["card"].winfo_exists():
            w["card"].destroy()
        if item in self.music_queue:
            self.music_queue.remove(item)
        if not self.music_queue:
            self._music_empty_label = tk.Label(
                self.queue_frame, bg=self.c["bg"], fg=self.c["muted"], font=self.font(9, italic=True),
                text=self.tr("music_queue_empty"), wraplength=660, justify="left")
            self._music_empty_label.pack(anchor="w", pady=8, padx=4)
        self._refresh_music_status()

    def _on_preview_click(self, item):
        btn = item["widgets"]["preview_btn"]
        if item.get("preview_path") and os.path.exists(item["preview_path"]):
            self.play_local_file(item["preview_path"], btn)
            return

        ytdlp_path = get_bin_path("yt-dlp.exe")
        ok, err_msg = check_tool_available(ytdlp_path, "yt-dlp.exe")
        if not ok:
            messagebox.showerror(self.tr("error_title"), err_msg)
            return
        ffmpeg_path = get_bin_path()
        btn.config(state="disabled", text=self.tr("music_preview_loading"))

        def worker():
            try:
                path = download_preview_clip(ytdlp_path, ffmpeg_path, item["link"])

                def done():
                    item["preview_path"] = path
                    btn.config(state="normal", text=self.tr("music_preview_btn"))
                    self.play_local_file(path, btn)

                self.root.after(0, done)
            except Exception as e:
                err_text = str(e)

                def fail(err_text=err_text):
                    btn.config(state="normal", text=self.tr("music_preview_btn"))
                    messagebox.showerror(self.tr("msg_preview_error_title"), err_text)

                self.root.after(0, fail)

        threading.Thread(target=worker, daemon=True).start()

    # -- Κατέβασμα όλης της (έτοιμης) ουράς -----------------------------
    def start_music_download(self):
        ready_items = [it for it in self.music_queue if it["status"] == "ready"]
        if not ready_items:
            messagebox.showerror(self.tr("error_title"), self.tr("music_err_no_ready"))
            return
        if any("list=" in it["link"] for it in ready_items):
            messagebox.showwarning(self.tr("music_warn_playlist_title"), self.tr("music_warn_playlist"))

        ytdlp_path = get_bin_path("yt-dlp.exe")
        ok, err_msg = check_tool_available(ytdlp_path, "yt-dlp.exe")
        if not ok:
            messagebox.showerror(self.tr("error_title"), err_msg)
            return
        ffmpeg_path = get_bin_path()

        audio_format = self.config.get("audio_format", "mp3")
        audio_bitrate = self.config.get("audio_bitrate", "0")
        audio_samplerate = self.config.get("audio_samplerate", "")

        self.cancel_requested = False
        self.download_all_btn.config(state="disabled")
        self.reset_queue_btn.config(state="disabled")
        self.analyze_btn.config(state="disabled")
        self.music_cancel_btn.config(state="normal")
        self.music_progress.configure(maximum=len(ready_items))
        self.music_progress.set(0)
        for it in ready_items:
            it["widgets"]["preview_btn"].config(state="disabled")
            it["widgets"]["remove_btn"].config(state="disabled")
            it["widgets"]["status_lbl"].config(text=self.tr("music_row_queued"), fg=self.STATUS_PENDING)

        def download_one(item):
            item["status"] = "downloading"
            output_template = os.path.join(self.config['music_path'], "%(title)s.%(ext)s")
            command = [
                ytdlp_path, "-x", "--audio-format", audio_format,
                "--ffmpeg-location", ffmpeg_path, "--no-playlist", "--no-warnings",
                "--retries", "5", "--fragment-retries", "5",
            ]
            if audio_format not in ("wav", "flac"):
                quality = "0" if audio_bitrate in ("0", "", "best") else f"{audio_bitrate}K"
                command += ["--audio-quality", quality]
            if audio_samplerate:
                command += ["--postprocessor-args", f"ffmpeg:-ar {audio_samplerate}"]
            command += ["-o", output_template, item["link"]]

            output_lines = []
            final_path = None
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, encoding='utf-8', errors='ignore',
                                            creationflags=run_flags())
                self.current_process = process
                for line in process.stdout:
                    output_lines.append(line)
                    dest_match = re.search(r'Destination:\s*(.+)', line)
                    if dest_match:
                        final_path = dest_match.group(1).strip()
                    if any(unit in line for unit in ("MiB/s", "KiB/s", "Mib/s", "Kib/s", "MB/s", "KB/s")):
                        match_speed = re.search(r'at\s+(\S+\s*/s)', line)
                        if match_speed:
                            spd = match_speed.group(1)
                            self.root.after(0, lambda s=spd: self.music_speed_lbl.config(text=f"⚡ {s}"))
                process.wait()
                tail = "".join(output_lines[-3:]).strip()
                return process.returncode == 0, tail, final_path
            except Exception as e:
                return False, str(e), None

        def run_batch():
            success_count = 0
            failed_items = []
            MAX_ATTEMPTS = 3

            for i, item in enumerate(ready_items):
                if self.cancel_requested:
                    break
                w = item["widgets"]
                self.root.after(0, lambda: self.music_speed_lbl.config(text=""))
                ok, tail, final_path = False, "", None

                for attempt in range(1, MAX_ATTEMPTS + 1):
                    if self.cancel_requested:
                        break
                    attempt_text = f" ({attempt}/{MAX_ATTEMPTS})" if attempt > 1 else ""
                    self.root.after(0, lambda i=i, a=attempt_text: self.music_status_lbl.config(
                        text=self.tr("music_status_downloading", i=i + 1, total=len(ready_items), attempt=a),
                        fg=self.STATUS_ACTIVE))
                    self.root.after(0, lambda w=w, a=attempt_text: w["status_lbl"].config(
                        text=self.tr("music_row_downloading", attempt=a), fg=self.STATUS_ACTIVE))

                    ok, tail, final_path = download_one(item)
                    if ok:
                        break
                    if attempt < MAX_ATTEMPTS and not self.cancel_requested:
                        wait_time = 8 * attempt
                        self.root.after(0, lambda i=i, wt=wait_time: self.music_status_lbl.config(
                            text=self.tr("music_status_retry_wait", i=i + 1, total=len(ready_items), wait=wt),
                            fg=self.STATUS_PENDING))
                        time.sleep(wait_time)

                if ok:
                    success_count += 1
                    item["status"] = "done"
                    item["downloaded_path"] = final_path
                    self.root.after(0, lambda item=item: self._mark_music_row_done(item))
                elif not self.cancel_requested:
                    item["status"] = "failed"
                    failed_items.append((item, tail))
                    self.root.after(0, lambda w=w, tail=tail: w["status_lbl"].config(
                        text=self.tr("music_row_failed", tail=tail[:60]), fg=self.STATUS_FAILED))

                self.root.after(0, lambda i=i: self.music_progress.set(i + 1))
                if i < len(ready_items) - 1 and not self.cancel_requested:
                    time.sleep(random.uniform(4, 9))

            self.current_process = None

            def finish():
                self.download_all_btn.config(state="normal")
                self.reset_queue_btn.config(state="normal")
                self.analyze_btn.config(state="normal")
                self.music_cancel_btn.config(state="disabled")
                for it in ready_items:
                    if it["status"] not in ("done",):
                        it["widgets"]["remove_btn"].config(state="normal")

                if self.cancel_requested:
                    self.music_status_lbl.config(
                        text=self.tr("music_status_cancelled", ok=success_count, total=len(ready_items)),
                        fg=self.STATUS_PENDING)
                    return
                if not failed_items:
                    self.music_status_lbl.config(
                        text=self.tr("music_status_all_done", ok=success_count, total=len(ready_items)),
                        fg=self.STATUS_DONE)
                else:
                    fail_summary = "\n".join(f"• {(it['title'] or it['link'])[:45]}...\n   ↳ {err[:120]}"
                                              for it, err in failed_items[:3])
                    self.music_status_lbl.config(
                        text=self.tr("music_status_partial_fail", ok=success_count, total=len(ready_items),
                                      summary=fail_summary),
                        fg=self.STATUS_PENDING)
            self.root.after(0, finish)

        threading.Thread(target=run_batch, daemon=True).start()

    def _mark_music_row_done(self, item):
        w = item["widgets"]
        if not w or not w["card"].winfo_exists():
            return
        w["status_lbl"].config(text=self.tr("music_row_done"), fg=self.STATUS_DONE)
        if item.get("downloaded_path") and os.path.exists(item["downloaded_path"]):
            play_btn = tk.Button(w["btn_col"], text=self.tr("music_play_btn"), font=self.font(8, "bold"),
                                  bg=self.STATUS_ACTIVE, fg="white", bd=0, padx=8, pady=4, cursor="hand2")
            play_btn.config(command=lambda p=item["downloaded_path"], b=play_btn: self.play_local_file(p, b))
            play_btn.pack(side="left", padx=3, before=w["remove_btn"])
            bind_hover_dynamic(play_btn)
            w["preview_btn"].destroy()
            w["play_btn"] = play_btn

    def cancel_music_download(self):
        self.stop_current_download()
        self.music_cancel_btn.config(state="disabled")

    # ------------------------------------------------------------------
    #  3. ΟΘΟΝΗ ΒΙΝΤΕΟ — thumbnail/τίτλος + πίνακας διαθέσιμων μορφών
    # ------------------------------------------------------------------
    AUDIO_MODES = {
        "Μέγιστη Συμβατότητα (AAC/M4A)": "bestaudio[ext=m4a]/bestaudio/best",
        "Καλύτερη Ποιότητα (Opus)": "bestaudio/best",
    }

    def show_video_screen(self):
        self.clear_container()
        self.cancel_requested = False
        c = self.c
        self.player.stop()
        self.video_meta = None
        self.video_link_resolved = None
        self.video_formats_by_iid = {}
        self.video_last_output_path = None

        self.build_header(self.tr("video_header_title"),
                           subtitle=self.tr("video_subtitle", path=self.config['video_path']),
                           accent=self.accent, on_back=self.show_dashboard)

        outer = ScrollableFrame(self.container, bg=c["bg"], fill_parent=True)
        outer.pack(fill="both", expand=True, padx=18, pady=(12, 10))
        body = outer.body

        tk.Label(body, text=self.tr("video_link_label"),
                 font=self.font(9), fg=c["muted"], bg=c["bg"], wraplength=680, justify="left").pack(anchor="w")

        link_row = tk.Frame(body, bg=c["bg"])
        link_row.pack(fill="x", pady=(6, 8))
        self.video_link_entry = tk.Entry(link_row, font=self.font(10), bg=c["input_bg"], fg=c["input_fg"],
                                          insertbackground=c["input_fg"], relief="flat", highlightthickness=1,
                                          highlightbackground=c["input_border"], highlightcolor=self.accent)
        self.video_link_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 8))
        self.video_link_entry.focus()
        add_right_click_paste(self.video_link_entry)
        self.video_check_btn = self._styled_button(link_row, self.tr("video_analyze_btn"), self.accent,
                                                      command=self.check_video_formats)
        self.video_check_btn.pack(side="left")
        self.video_reset_btn = self._styled_button(link_row, self.tr("clear_btn"), c["btn_bg"], fg=c["fg"],
                                                      command=self.reset_video_screen)
        self.video_reset_btn.pack(side="left", padx=(8, 0))

        # -- κάρτα με εξώφυλλο/τίτλο/uploader/διάρκεια, γεμίζει μετά την ανάλυση --
        self.video_info_card = tk.Frame(body, bg=c["card_bg"], highlightthickness=1,
                                         highlightbackground=c["card_border"])
        self.video_info_card.pack(fill="x", pady=(0, 10))
        info_inner = tk.Frame(self.video_info_card, bg=c["card_bg"])
        info_inner.pack(fill="x", padx=10, pady=8)
        self.video_thumb_holder = tk.Frame(info_inner, bg=c["track_bg"], width=110, height=62)
        self.video_thumb_holder.pack(side="left")
        self.video_thumb_holder.pack_propagate(False)
        self.video_thumb_lbl = tk.Label(self.video_thumb_holder, text="🎬", font=self.font(24),
                                         bg=c["track_bg"], fg=c["fg"])
        self.video_thumb_lbl.pack(fill="both", expand=True)
        vtext_col = tk.Frame(info_inner, bg=c["card_bg"])
        vtext_col.pack(side="left", fill="x", expand=True, padx=(10, 0))
        self.video_title_lbl = tk.Label(vtext_col, text=self.tr("video_placeholder_title"),
                                         font=self.font(10, "bold"), fg=c["fg"], bg=c["card_bg"],
                                         anchor="w", wraplength=520, justify="left")
        self.video_title_lbl.pack(fill="x", anchor="w")
        self.video_meta_lbl = tk.Label(vtext_col, text="", font=self.font(8), fg=c["muted"],
                                        bg=c["card_bg"], anchor="w")
        self.video_meta_lbl.pack(fill="x", anchor="w")

        # -- γρήγορες επιλογές ποιότητας --
        preset_row = tk.Frame(body, bg=c["bg"])
        preset_row.pack(fill="x", pady=(0, 6))
        tk.Label(preset_row, text=self.tr("video_preset_label"), font=self.font(8), fg=c["muted"],
                  bg=c["bg"]).pack(side="left")
        for label, key in ((self.tr("video_preset_best"), "best"), ("1080p", 1080), ("720p", 720),
                           ("480p", 480), (self.tr("video_preset_audio"), "audio")):
            b = tk.Button(preset_row, text=label, font=self.font(8, "bold"), bg=c["btn_bg"], fg=c["fg"],
                          bd=0, padx=8, pady=4, cursor="hand2",
                          command=lambda k=key: self.apply_quality_preset(k))
            b.pack(side="left", padx=3)
            bind_hover(b, c["btn_bg"], c["btn_hover"])

        # -- πίνακας μορφών --
        table_frame = tk.Frame(body, bg=c["bg"])
        table_frame.pack(fill="x")
        columns = ("quality", "resolution", "ext", "fps", "size", "video", "audio")
        headers = {"quality": self.tr("video_col_quality"), "resolution": self.tr("video_col_resolution"),
                   "ext": self.tr("video_col_ext"), "fps": self.tr("video_col_fps"),
                   "size": self.tr("video_col_size"), "video": self.tr("video_col_video"),
                   "audio": self.tr("video_col_audio")}
        widths = {"quality": 130, "resolution": 90, "ext": 50, "fps": 40, "size": 65, "video": 100, "audio": 105}
        self.format_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=7,
                                         selectmode="browse")
        for col in columns:
            self.format_tree.heading(col, text=headers[col])
            self.format_tree.column(col, width=widths[col], anchor="w")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.format_tree.yview)
        self.format_tree.configure(yscrollcommand=vsb.set)
        self.format_tree.pack(side="left", fill="x", expand=True)
        vsb.pack(side="right", fill="y")
        self.format_tree.insert("", "end", iid="__placeholder__",
                                 values=("—", "—", "—", "—", "—", "—", "—"))

        audio_row = tk.Frame(body, bg=c["bg"])
        audio_row.pack(fill="x", pady=(8, 4))
        tk.Label(audio_row, text=self.tr("video_audio_mix_label"), fg=c["fg"], bg=c["bg"],
                 font=self.font(9)).pack(side="left", padx=(0, 6))
        self.audio_mode_var = tk.StringVar(value=list(self.AUDIO_MODES.keys())[0])
        audio_combo = ttk.Combobox(audio_row, textvariable=self.audio_mode_var,
                                    values=list(self.AUDIO_MODES.keys()), state="readonly", width=28)
        audio_combo.pack(side="left")

        status_area = tk.Frame(body, bg=c["bg"])
        status_area.pack(fill="x", pady=(6, 0))
        self.video_status_lbl = tk.Label(status_area, text="", font=self.font(9, "bold"), bg=c["bg"], fg=c["fg"],
                                          wraplength=680, justify="left")
        self.video_status_lbl.pack(anchor="w")
        self.video_progress = GradientProgressBar(status_area, width=450, height=16, bg=c["bg"],
                                                    trough=c["track_bg"], accent=self.STATUS_DONE)
        self.video_progress.pack(fill="x", pady=(6, 2))
        self.video_progress.configure(maximum=100)
        self.video_speed_lbl = tk.Label(status_area, text="", font=self.font(9, italic=True), fg=self.STATUS_ACTIVE,
                                         bg=c["bg"])
        self.video_speed_lbl.pack(anchor="w")

        btn_row = tk.Frame(body, bg=c["bg"])
        btn_row.pack(pady=(10, 0))
        self.video_dl_btn = self._styled_button(btn_row, self.tr("video_dl_btn"), self.STATUS_DONE,
                                                   command=self.start_video_download)
        self.video_dl_btn.grid(row=0, column=0, padx=5)
        self.video_dl_btn.config(state="disabled")
        self.video_cancel_btn = self._styled_button(btn_row, self.tr("video_cancel_btn"), self.ACCENT_DANGER,
                                                       command=self.cancel_video_download)
        self.video_cancel_btn.grid(row=0, column=1, padx=5)
        self.video_cancel_btn.config(state="disabled")

        self.video_result_row = tk.Frame(body, bg=c["bg"])
        self.video_result_row.pack(pady=(8, 0))

    def reset_video_screen(self):
        """ Καθαρίζει το πεδίο link και επαναφέρει όλη την οθόνη Video στην αρχική
        της κατάσταση — ίδια λογική με το «Νέα Λίστα» της Μουσικής. """
        self.player.stop()
        self.video_link_entry.delete(0, tk.END)
        self.video_meta = None
        self.video_link_resolved = None
        self.video_formats_by_iid = {}
        self.video_last_output_path = None
        self.video_thumb_lbl.configure(image="", text="🎬")
        self.video_thumb_lbl.image = None
        self.video_title_lbl.config(text=self.tr("video_placeholder_title"))
        self.video_meta_lbl.config(text="")
        for row in self.format_tree.get_children():
            self.format_tree.delete(row)
        self.format_tree.insert("", "end", iid="__placeholder__",
                                 values=("—", "—", "—", "—", "—", "—", "—"))
        self.video_status_lbl.config(text="")
        self.video_progress.set(0)
        self.video_speed_lbl.config(text="")
        self.video_dl_btn.config(state="disabled")
        self.video_check_btn.config(state="normal", text=self.tr("video_analyze_btn"))
        for w in self.video_result_row.winfo_children():
            w.destroy()
        self.video_link_entry.focus()

    # -- Ανάλυση link: metadata + διαθέσιμες μορφές -----------------
    def check_video_formats(self):
        raw_link = self.video_link_entry.get().strip()
        if not raw_link:
            messagebox.showerror(self.tr("error_title"), self.tr("video_err_no_link"))
            return
        ytdlp_path = get_bin_path("yt-dlp.exe")
        ok, err_msg = check_tool_available(ytdlp_path, "yt-dlp.exe")
        if not ok:
            messagebox.showerror(self.tr("error_title"), err_msg)
            return

        link = clean_link(raw_link)
        self.video_check_btn.config(state="disabled", text=self.tr("video_analyzing_btn"))
        self.video_dl_btn.config(state="disabled")
        self.video_status_lbl.config(text=self.tr("video_status_analyzing"), fg=self.STATUS_ACTIVE)
        self.video_title_lbl.config(text=self.tr("video_analyzing_btn"))
        self.video_meta_lbl.config(text="")
        for row in self.format_tree.get_children():
            self.format_tree.delete(row)
        self.video_formats_by_iid = {}
        for w in self.video_result_row.winfo_children():
            w.destroy()

        def worker():
            try:
                meta = fetch_metadata(ytdlp_path, link)
            except Exception as e:
                err_text = str(e)
                self.root.after(0, lambda err_text=err_text: self._video_analysis_failed(err_text))
                return
            pil_thumb = download_thumbnail_pil(meta.get("thumbnail"), size=(110, 62))
            self.root.after(0, lambda: self._video_analysis_done(meta, pil_thumb, link))

        threading.Thread(target=worker, daemon=True).start()

    def _video_analysis_failed(self, error_text):
        self.video_check_btn.config(state="normal", text=self.tr("video_analyze_btn"))
        self.video_title_lbl.config(text=self.tr("music_row_analysis_failed"))
        self.video_meta_lbl.config(text="")
        self.video_status_lbl.config(text=self.tr("video_status_analysis_failed", err=error_text),
                                      fg=self.STATUS_FAILED)

    def _video_analysis_done(self, meta, pil_thumb, link):
        self.video_meta = meta
        self.video_link_resolved = link
        self.video_check_btn.config(state="normal", text=self.tr("video_analyze_btn"))

        photo = pil_to_photo(pil_thumb)
        if photo:
            self.video_thumb_lbl.configure(image=photo, text="")
            self.video_thumb_lbl.image = photo
        else:
            _name, icon = guess_platform(link)
            self.video_thumb_lbl.configure(text=icon)

        title = meta["title"] or link
        self.video_title_lbl.config(text=title)
        platform_name, _icon = guess_platform(link)
        bits = [platform_name]
        if meta.get("uploader"):
            bits.append(meta["uploader"])
        bits.append(human_duration(meta.get("duration")))
        self.video_meta_lbl.config(text=" • ".join(bits))

        for row in self.format_tree.get_children():
            self.format_tree.delete(row)
        self.video_formats_by_iid = {}

        self.format_tree.insert("", "end", iid="audio_only",
                                 values=(self.tr("video_audio_only_row"), "—", "mp3", "—", "—", "—", "best"))
        self.video_formats_by_iid["audio_only"] = {"audio_only": True}

        formats = meta.get("formats") or []
        usable = []
        for f in formats:
            vcodec = f.get("vcodec") or "none"
            note = (f.get("format_note") or "").lower()
            if vcodec == "none":
                continue
            if "storyboard" in note or f.get("ext") == "mhtml":
                continue
            usable.append(f)
        usable.sort(key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)

        for f in usable:
            fmt_id = f.get("format_id")
            if not fmt_id:
                continue
            height = f.get("height")
            quality = f.get("format_note") or (f"{height}p" if height else fmt_id)
            resolution = f.get("resolution") or (f"{f.get('width')}x{height}" if f.get("width") and height else "—")
            ext = f.get("ext") or "—"
            fps = f.get("fps") or "—"
            size = human_filesize(f.get("filesize") or f.get("filesize_approx"))
            vcodec = (f.get("vcodec") or "—")
            acodec = f.get("acodec") or "none"
            audio_label = (acodec[:14] if acodec and acodec != "none" else self.tr("video_no_audio"))
            iid = f"fmt_{fmt_id}"
            self.format_tree.insert("", "end", iid=iid,
                                     values=(quality, resolution, ext, fps, size, vcodec[:14], audio_label))
            self.video_formats_by_iid[iid] = f

        if usable:
            first_iid = f"fmt_{usable[0].get('format_id')}"
            self.format_tree.selection_set(first_iid)
            self.format_tree.see(first_iid)
            self.video_status_lbl.config(text=self.tr("video_status_ready"), fg=self.STATUS_PENDING)
        else:
            self.video_status_lbl.config(text=self.tr("video_status_no_formats"), fg=self.STATUS_PENDING)
        self.video_dl_btn.config(state="normal")

    def apply_quality_preset(self, key):
        if not self.video_formats_by_iid:
            return
        if key == "audio":
            self.format_tree.selection_set("audio_only")
            self.format_tree.see("audio_only")
            return
        candidates = [(iid, f) for iid, f in self.video_formats_by_iid.items() if not f.get("audio_only")]
        if not candidates:
            return
        if key == "best":
            best_iid = max(candidates, key=lambda kv: (kv[1].get("height") or 0, kv[1].get("tbr") or 0))[0]
        else:
            target = int(key)
            best_iid = min(candidates, key=lambda kv: abs((kv[1].get("height") or 0) - target))[0]
        self.format_tree.selection_set(best_iid)
        self.format_tree.see(best_iid)

    # -- Κατέβασμα επιλεγμένης μορφής --------------------------------
    def start_video_download(self):
        if not self.video_meta or not self.video_link_resolved:
            messagebox.showerror(self.tr("error_title"), self.tr("video_err_no_analysis"))
            return
        sel = self.format_tree.selection()
        if not sel:
            messagebox.showerror(self.tr("error_title"), self.tr("video_err_no_format"))
            return
        iid = sel[0]
        fmt = self.video_formats_by_iid.get(iid)
        if fmt is None:
            messagebox.showerror(self.tr("error_title"), self.tr("video_err_bad_selection"))
            return

        ytdlp_path = get_bin_path("yt-dlp.exe")
        ok, err_msg = check_tool_available(ytdlp_path, "yt-dlp.exe")
        if not ok:
            messagebox.showerror(self.tr("error_title"), err_msg)
            return
        ffmpeg_path = get_bin_path()

        self.cancel_requested = False
        self.video_status_lbl.config(text=self.tr("video_status_downloading"), fg=self.STATUS_ACTIVE)
        self.video_progress.set(0)
        self.video_speed_lbl.config(text="")
        self.video_dl_btn.config(state="disabled")
        self.video_check_btn.config(state="disabled")
        self.video_reset_btn.config(state="disabled")
        self.video_cancel_btn.config(state="normal")
        for w in self.video_result_row.winfo_children():
            w.destroy()

        link = self.video_link_resolved
        is_audio_only = bool(fmt.get("audio_only"))

        def run():
            output_template = os.path.join(self.config['video_path'],
                                             "%(title)s.%(ext)s" if is_audio_only
                                             else "%(title)s [%(resolution)s].%(ext)s")
            if is_audio_only:
                command = [
                    ytdlp_path, "-x", "--audio-format", "mp3", "--audio-quality", "0",
                    "--ffmpeg-location", ffmpeg_path, "--no-playlist", "--no-warnings",
                    "-o", output_template, link,
                ]
            else:
                acodec = fmt.get("acodec") or "none"
                fmt_id = fmt.get("format_id")
                if acodec != "none":
                    fmt_selector = fmt_id  # η μορφή έχει ήδη ήχο — δεν χρειάζεται merge
                else:
                    audio_selector = self.AUDIO_MODES[self.audio_mode_var.get()]
                    fmt_selector = f"{fmt_id}+{audio_selector}"
                command = [
                    ytdlp_path, "-f", fmt_selector, "--ffmpeg-location", ffmpeg_path,
                    "--merge-output-format", "mp4", "--no-playlist", "--no-warnings",
                    "-o", output_template, link,
                ]

            output_lines = []
            final_path = None
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, encoding='utf-8', errors='ignore',
                                            creationflags=run_flags())
                self.current_process = process

                for line in process.stdout:
                    output_lines.append(line)
                    dest_match = re.search(r'Destination:\s*(.+)', line)
                    if dest_match:
                        final_path = dest_match.group(1).strip()
                    merge_match = re.search(r'Merging formats into\s+"(.+)"', line)
                    if merge_match:
                        final_path = merge_match.group(1).strip()
                    if any(unit in line for unit in ("MiB/s", "KiB/s", "Mib/s", "Kib/s", "MB/s", "KB/s")):
                        match_speed = re.search(r'at\s+(\S+\s*/s)', line)
                        if match_speed:
                            spd = match_speed.group(1)
                            self.root.after(0, lambda s=spd: self.video_speed_lbl.config(text=f"⚡ {s}"))
                    match_pct = re.search(r'(\d+\.?\d*)%', line)
                    if match_pct and any(unit in line for unit in ("MiB/s", "KiB/s", "Mib/s", "Kib/s", "MB/s", "KB/s")):
                        pct = float(match_pct.group(1))
                        self.root.after(0, lambda p=pct: self.video_progress.set(p))

                process.wait()

                if self.cancel_requested:
                    self.root.after(0, lambda: self.video_status_lbl.config(
                        text=self.tr("video_status_cancelled"), fg=self.STATUS_PENDING))
                elif process.returncode == 0:
                    self.video_last_output_path = final_path
                    self.root.after(0, lambda: self._video_download_success(final_path))
                else:
                    tail = "".join(output_lines[-6:]).strip()
                    self.root.after(0, lambda: self.video_status_lbl.config(
                        text=self.tr("video_status_error", tail=tail), fg=self.STATUS_FAILED))
            except Exception as e:
                err_text = str(e)
                self.root.after(0, lambda err_text=err_text: self.video_status_lbl.config(
                    text=self.tr("video_status_error_short", err=err_text), fg=self.STATUS_FAILED))
            finally:
                self.current_process = None
                self.root.after(0, lambda: [
                    self.video_dl_btn.config(state="normal"),
                    self.video_check_btn.config(state="normal"),
                    self.video_reset_btn.config(state="normal"),
                    self.video_cancel_btn.config(state="disabled"),
                ])

        threading.Thread(target=run, daemon=True).start()

    def _video_download_success(self, final_path):
        self.video_status_lbl.config(text=self.tr("video_status_done"), fg=self.STATUS_DONE)
        self.video_progress.set(100)
        self.video_speed_lbl.config(text="✔")

        folder_btn = self._styled_button(self.video_result_row, self.tr("video_open_folder_btn"), self.c["btn_bg"],
                                           fg=self.c["fg"],
                                           command=lambda: self._open_path(self.config['video_path']))
        folder_btn.pack(side="left", padx=4)
        if final_path and os.path.exists(final_path):
            open_btn = self._styled_button(self.video_result_row, self.tr("video_open_file_btn"), self.c["btn_bg"],
                                             fg=self.c["fg"],
                                             command=lambda: self._open_path(final_path))
            open_btn.pack(side="left", padx=4)
            if final_path.lower().endswith((".mp3", ".m4a", ".opus", ".ogg", ".wav")):
                play_btn = tk.Button(self.video_result_row, text=self.tr("video_play_here_btn"),
                                      font=self.font(9, "bold"),
                                      bg=self.STATUS_ACTIVE, fg="white", bd=0, padx=10, pady=6, cursor="hand2")
                play_btn.config(command=lambda p=final_path, b=play_btn: self.play_local_file(p, b))
                play_btn.pack(side="left", padx=4)
                bind_hover_dynamic(play_btn)

    def cancel_video_download(self):
        self.stop_current_download()
        self.video_cancel_btn.config(state="disabled")

    # ------------------------------------------------------------------
    #  4. ΟΘΟΝΗ ΡΥΘΜΙΣΕΩΝ — ομαδοποιημένες ενότητες, καθαρά ξεχωριστές
    # ------------------------------------------------------------------
    def show_settings_screen(self):
        self.clear_container()
        c = self.c
        self.player.stop()

        self.build_header(self.tr("settings_header_title"), subtitle=self.tr("settings_subtitle"),
                           accent=self.ACCENT_SETTINGS, on_back=self.show_dashboard)

        outer = ScrollableFrame(self.container, bg=c["bg"], fill_parent=True)
        outer.pack(fill="both", expand=True, padx=18, pady=14)
        body = outer.body

        # ---- Ενότητα: Εμφάνιση (θέμα + χρώμα εφαρμογής) ----
        sec = self._make_section(body, "🎨", self.tr("settings_appearance"), self.ACCENT_SETTINGS)
        theme_row = tk.Frame(sec, bg=c["card_bg"])
        theme_row.pack(fill="x")
        is_dark = self.config.get("theme") == "dark"
        theme_now = self.tr("settings_theme_dark") if is_dark else self.tr("settings_theme_light")
        tk.Label(theme_row, text=self.tr("settings_theme_current", theme=theme_now),
                 font=self.font(9), fg=c["muted"], bg=c["card_bg"]).pack(side="left")
        theme_next = self.tr("settings_theme_light") if is_dark else self.tr("settings_theme_dark")
        self._styled_button(theme_row, self.tr("settings_theme_switch_to", theme=theme_next),
                             self.ACCENT_SETTINGS, command=self.toggle_theme).pack(side="right")

        ttk.Separator(sec, orient="horizontal").pack(fill="x", pady=10)

        accent_row = tk.Frame(sec, bg=c["card_bg"])
        accent_row.pack(fill="x")
        tk.Label(accent_row, text=self.tr("settings_accent"), font=self.font(9, "bold"), fg=c["fg"],
                 bg=c["card_bg"], anchor="w").pack(fill="x")
        tk.Label(accent_row, text=self.tr("settings_accent_desc"), font=self.font(8), fg=c["muted"],
                 bg=c["card_bg"], anchor="w", wraplength=480, justify="left").pack(fill="x", pady=(0, 8))

        swatch_row = tk.Frame(accent_row, bg=c["card_bg"])
        swatch_row.pack(fill="x", anchor="w")
        current_accent = self.accent
        for name, hex_color in self.ACCENT_PRESETS:
            self._build_accent_swatch(swatch_row, hex_color, current_accent)
        self._styled_button(accent_row, self.tr("settings_accent_custom_btn"), c["btn_bg"], fg=c["fg"],
                             command=self.pick_custom_accent_color).pack(anchor="w", pady=(10, 0))

        # ---- Ενότητα: Γλώσσα ----
        sec = self._make_section(body, "🌐", self.tr("settings_language"), self.ACCENT_MUSIC)
        tk.Label(sec, text=self.tr("settings_language_desc"), font=self.font(8), fg=c["muted"],
                 bg=c["card_bg"], anchor="w", wraplength=480, justify="left").pack(fill="x", pady=(0, 8))
        lang_row = tk.Frame(sec, bg=c["card_bg"])
        lang_row.pack(fill="x", anchor="w")
        cur_lang = self.lang
        el_btn = tk.Button(lang_row, text="🇬🇷 Ελληνικά", font=self.font(9, "bold"),
                            bg=(self.accent if cur_lang == "el" else c["btn_bg"]),
                            fg=("white" if cur_lang == "el" else c["fg"]), bd=0, padx=14, pady=7,
                            cursor="hand2", command=lambda: self.set_language("el"))
        el_btn.pack(side="left", padx=(0, 8))
        en_btn = tk.Button(lang_row, text="🇬🇧 English", font=self.font(9, "bold"),
                            bg=(self.accent if cur_lang == "en" else c["btn_bg"]),
                            fg=("white" if cur_lang == "en" else c["fg"]), bd=0, padx=14, pady=7,
                            cursor="hand2", command=lambda: self.set_language("en"))
        en_btn.pack(side="left")
        if cur_lang != "el":
            bind_hover(el_btn, c["btn_bg"], c["btn_hover"])
        if cur_lang != "en":
            bind_hover(en_btn, c["btn_bg"], c["btn_hover"])

        # ---- Ενότητα: Ενημερώσεις ----
        sec = self._make_section(body, "🔄", self.tr("settings_updates"), self.ACCENT_VIDEO)
        last_check = self.config.get("last_ytdlp_check", "")
        check_text = self.tr("settings_last_check", date=last_check) if last_check else self.tr("settings_never_checked")
        row1 = tk.Frame(sec, bg=c["card_bg"])
        row1.pack(fill="x", pady=(0, 10))
        col1 = tk.Frame(row1, bg=c["card_bg"])
        col1.pack(side="left", fill="x", expand=True)
        tk.Label(col1, text=self.tr("settings_ytdlp_engine"), font=self.font(9, "bold"), fg=c["fg"],
                 bg=c["card_bg"], anchor="w").pack(fill="x")
        tk.Label(col1, text=check_text, font=self.font(8), fg=c["muted"], bg=c["card_bg"],
                 anchor="w").pack(fill="x")
        self.ytdlp_update_btn = self._styled_button(row1, self.tr("settings_check_now"), c["btn_bg"], fg=c["fg"],
                                                       command=self.do_manual_ytdlp_update)
        self.ytdlp_update_btn.pack(side="right")

        self.auto_ytdlp_var = tk.BooleanVar(value=self.config.get("auto_update_ytdlp", True))
        tk.Checkbutton(sec, text=self.tr("settings_ytdlp_autoupdate"), variable=self.auto_ytdlp_var,
                       font=self.font(8), fg=c["muted"], bg=c["card_bg"], activebackground=c["card_bg"],
                       activeforeground=c["fg"], selectcolor=c["input_bg"], bd=0, highlightthickness=0,
                       anchor="w", wraplength=480, justify="left", cursor="hand2",
                       command=self.toggle_auto_ytdlp_update).pack(fill="x", anchor="w", pady=(2, 0))

        ttk.Separator(sec, orient="horizontal").pack(fill="x", pady=6)

        row2 = tk.Frame(sec, bg=c["card_bg"])
        row2.pack(fill="x")
        col2 = tk.Frame(row2, bg=c["card_bg"])
        col2.pack(side="left", fill="x", expand=True)
        tk.Label(col2, text=self.tr("settings_app_version"), font=self.font(9, "bold"), fg=c["fg"],
                 bg=c["card_bg"], anchor="w").pack(fill="x")
        tk.Label(col2, text=f"v{APP_VERSION}", font=self.font(8), fg=c["muted"], bg=c["card_bg"],
                 anchor="w").pack(fill="x")
        self.app_update_btn = self._styled_button(row2, self.tr("settings_check_new_version"), c["btn_bg"],
                                                     fg=c["fg"], command=self.do_manual_app_check)
        self.app_update_btn.pack(side="right")

        self.auto_app_check_var = tk.BooleanVar(value=self.config.get("auto_check_app_update", True))
        tk.Checkbutton(sec, text=self.tr("settings_app_autocheck"), variable=self.auto_app_check_var,
                       font=self.font(8), fg=c["muted"], bg=c["card_bg"], activebackground=c["card_bg"],
                       activeforeground=c["fg"], selectcolor=c["input_bg"], bd=0, highlightthickness=0,
                       anchor="w", wraplength=480, justify="left", cursor="hand2",
                       command=self.toggle_auto_app_check).pack(fill="x", anchor="w", pady=(6, 0))

        # ---- Ενότητα: Φάκελοι ----
        sec = self._make_section(body, "📁", self.tr("settings_folders"), self.ACCENT_MUSIC)
        row_m = tk.Frame(sec, bg=c["card_bg"])
        row_m.pack(fill="x", pady=(0, 10))
        colm = tk.Frame(row_m, bg=c["card_bg"])
        colm.pack(side="left", fill="x", expand=True)
        tk.Label(colm, text=self.tr("settings_music_folder"), font=self.font(9, "bold"), fg=c["fg"],
                 bg=c["card_bg"], anchor="w").pack(fill="x")
        self.music_path_lbl = tk.Label(colm, text=self.config['music_path'], font=self.font(8),
                                        fg=c["muted"], bg=c["card_bg"], anchor="w", wraplength=440,
                                        justify="left")
        self.music_path_lbl.pack(fill="x")
        self._styled_button(row_m, self.tr("settings_change_btn"), c["btn_bg"], fg=c["fg"],
                             command=self.change_music_folder).pack(side="right")

        ttk.Separator(sec, orient="horizontal").pack(fill="x", pady=6)

        row_v = tk.Frame(sec, bg=c["card_bg"])
        row_v.pack(fill="x")
        colv = tk.Frame(row_v, bg=c["card_bg"])
        colv.pack(side="left", fill="x", expand=True)
        tk.Label(colv, text=self.tr("settings_video_folder"), font=self.font(9, "bold"), fg=c["fg"],
                 bg=c["card_bg"], anchor="w").pack(fill="x")
        self.video_path_lbl = tk.Label(colv, text=self.config['video_path'], font=self.font(8),
                                        fg=c["muted"], bg=c["card_bg"], anchor="w", wraplength=440,
                                        justify="left")
        self.video_path_lbl.pack(fill="x")
        self._styled_button(row_v, self.tr("settings_change_btn"), c["btn_bg"], fg=c["fg"],
                             command=self.change_video_folder).pack(side="right")

        # ---- Ενότητα: Επικίνδυνη ζώνη ----
        sec = self._make_section(body, "⚠️", self.tr("settings_reset"), self.ACCENT_DANGER)
        tk.Label(sec, text=self.tr("settings_reset_desc"),
                 font=self.font(8), fg=c["muted"], bg=c["card_bg"], wraplength=480, justify="left").pack(
            anchor="w", pady=(0, 8))
        self._styled_button(sec, self.tr("settings_reset_btn"), self.ACCENT_DANGER,
                             command=self.reset_settings).pack(anchor="w")

        footer = tk.Label(self.container, text=self.tr("settings_footer", version=APP_VERSION),
                           font=self.font(8), fg=c["muted"], bg=c["bg"])
        footer.pack(side="bottom", pady=8)

    def _build_accent_swatch(self, parent, hex_color, current_accent):
        c = self.c
        selected = (hex_color.lower() == (current_accent or "").lower())
        holder = tk.Frame(parent, bg=(hex_color if not selected else c["fg"]))
        holder.pack(side="left", padx=4)
        inner_pad = 3 if selected else 0
        swatch = tk.Button(holder, text=("✓" if selected else ""), font=self.font(11, "bold"),
                            bg=hex_color, fg="white", activebackground=hex_color, bd=0,
                            width=3, height=1, cursor="hand2",
                            command=lambda hc=hex_color: self.set_accent_color(hc))
        swatch.pack(padx=inner_pad, pady=inner_pad)

    def set_accent_color(self, hex_color):
        self.config["accent_color"] = hex_color
        save_config(self.config)
        self.show_settings_screen()

    def pick_custom_accent_color(self):
        _rgb, hex_color = colorchooser.askcolor(color=self.accent, title=self.tr("settings_accent_custom_btn"))
        if hex_color:
            self.set_accent_color(hex_color)

    def set_language(self, lang_code):
        if self.config.get("language") == lang_code:
            return
        self.config["language"] = lang_code
        save_config(self.config)
        self.root.title(self.tr("app_title"))
        self.show_settings_screen()

    def _make_section(self, parent, icon, title, accent):
        c = self.c
        card = tk.Frame(parent, bg=c["card_bg"], highlightthickness=1, highlightbackground=c["card_border"])
        card.pack(fill="x", pady=8)
        head = tk.Frame(card, bg=c["card_bg"])
        head.pack(fill="x", padx=14, pady=(12, 6))
        tk.Frame(head, bg=accent, width=4, height=18).pack(side="left", padx=(0, 8))
        tk.Label(head, text=f"{icon}  {title}", font=self.font(11, "bold"), fg=c["fg"],
                 bg=c["card_bg"]).pack(side="left")
        ttk.Separator(card, orient="horizontal").pack(fill="x", padx=14)
        body = tk.Frame(card, bg=c["card_bg"])
        body.pack(fill="x", padx=14, pady=12)
        return body

    def toggle_theme(self):
        self.config["theme"] = "light" if self.config.get("theme") == "dark" else "dark"
        save_config(self.config)
        self.show_settings_screen()

    def toggle_auto_ytdlp_update(self):
        self.config["auto_update_ytdlp"] = self.auto_ytdlp_var.get()
        save_config(self.config)

    def toggle_auto_app_check(self):
        self.config["auto_check_app_update"] = self.auto_app_check_var.get()
        save_config(self.config)

    def change_music_folder(self):
        new_dir = filedialog.askdirectory()
        if new_dir:
            self.config['music_path'] = new_dir
            save_config(self.config)
            self.music_path_lbl.config(text=self.config['music_path'])

    def change_video_folder(self):
        new_dir = filedialog.askdirectory()
        if new_dir:
            self.config['video_path'] = new_dir
            save_config(self.config)
            self.video_path_lbl.config(text=self.config['video_path'])

    def reset_settings(self):
        if not messagebox.askyesno(self.tr("settings_reset_confirm_title"), self.tr("settings_reset_confirm")):
            return
        self.config = dict(DEFAULT_CONFIG)
        save_config(self.config)
        messagebox.showinfo(self.tr("settings_reset_done_title"), self.tr("settings_reset_done"))
        self.show_settings_screen()

    def do_manual_ytdlp_update(self):
        self.ytdlp_update_btn.config(state="disabled", text=self.tr("settings_checking"))

        def run():
            success, output = run_ytdlp_self_update()
            self.config["last_ytdlp_check"] = datetime.now().strftime("%Y-%m-%d")
            save_config(self.config)

            def show_result():
                if not self.ytdlp_update_btn.winfo_exists():
                    return
                if success:
                    if "up to date" in output.lower() or "already" in output.lower():
                        messagebox.showinfo(self.tr("msg_ytdlp_up_to_date_title"), self.tr("msg_ytdlp_up_to_date"))
                    else:
                        messagebox.showinfo(self.tr("msg_ytdlp_done_title"),
                                             self.tr("msg_ytdlp_done", output=output[-400:]))
                else:
                    messagebox.showerror(self.tr("msg_ytdlp_update_error_title"), output)
                self.show_settings_screen()

            self.root.after(0, show_result)

        threading.Thread(target=run, daemon=True).start()

    def do_manual_app_check(self):
        self.app_update_btn.config(state="disabled", text=self.tr("settings_checking"))

        def run():
            update_data = check_for_app_update()

            def show_result():
                if not self.app_update_btn.winfo_exists():
                    return
                self.app_update_btn.config(state="normal", text=self.tr("settings_check_new_version"))
                if not update_data:
                    messagebox.showerror(self.tr("msg_app_check_error_title"), self.tr("msg_app_check_error"))
                    return
                remote_ver = update_data.get("version", "")
                if parse_version(remote_ver) > parse_version(APP_VERSION):
                    self.prompt_and_apply_update(update_data)
                else:
                    messagebox.showinfo(self.tr("msg_app_up_to_date_title"),
                                         self.tr("msg_app_up_to_date", version=APP_VERSION))

            self.root.after(0, show_result)

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------------
    #  Αυτόματοι έλεγχοι ενημέρωσης κατά την εκκίνηση
    # ------------------------------------------------------------------
    def check_app_update_silent(self):
        if not self.config.get("auto_check_app_update", True):
            return

        def run():
            update_data = check_for_app_update()
            if update_data and parse_version(update_data.get("version", "0")) > parse_version(APP_VERSION):
                self.root.after(0, lambda: self.prompt_and_apply_update(update_data))
        threading.Thread(target=run, daemon=True).start()


    def prompt_and_apply_update(self, update_info):
        version = update_info.get("version", "?")
        notes = update_info.get("notes", "")
        download_url = update_info.get("download_url", "")

        msg = self.tr("msg_update_found", version=version, current=APP_VERSION)
        if notes:
            msg += self.tr("msg_update_whats_new", notes=notes)

        if not download_url or not IS_WRITABLE_INSTALL:
            # Είτε δεν υπάρχει αυτόματο link λήψης, είτε το πρόγραμμα είναι εγκατεστημένο σε
            # προστατευμένο φάκελο (π.χ. Program Files) όπου η αυτόματη αντικατάσταση του .exe
            # θα απαιτούσε δικαιώματα διαχειριστή — σε αυτή την περίπτωση απλά ανοίγουμε τη
            # σελίδα λήψης αντί να προσπαθήσουμε κάτι που ξέρουμε ότι θα αποτύχει.
            if not IS_WRITABLE_INSTALL and download_url:
                msg += self.tr("msg_update_protected_folder")
            else:
                msg += self.tr("msg_update_no_auto_link")
            if messagebox.askyesno(self.tr("msg_update_available_title"), msg):
                url = update_info.get("url", "") or download_url
                if url:
                    webbrowser.open(url)
            return

        msg += self.tr("msg_update_confirm_now")
        if not messagebox.askyesno(self.tr("msg_update_available_title"), msg):
            return

        progress_win = tk.Toplevel(self.root)
        progress_win.title(self.tr("msg_update_progress_title"))
        progress_win.geometry("320x100")
        progress_win.resizable(False, False)
        self._apply_icon(progress_win)
        tk.Label(progress_win, text=self.tr("msg_update_progress"), pady=20).pack()
        progress_win.grab_set()

        def do_update():
            success, err = download_and_apply_update(download_url)

            def finish():
                if success:
                    self.root.destroy()
                else:
                    progress_win.destroy()
                    messagebox.showerror(self.tr("msg_update_error_title"), err)
            self.root.after(0, finish)

        threading.Thread(target=do_update, daemon=True).start()

    def maybe_auto_update_ytdlp(self):
        if not self.config.get("auto_update_ytdlp", True):
            return
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
                    self.tr("msg_ytdlp_auto_updated_title"), self.tr("msg_ytdlp_auto_updated")))
        threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":
    is_primary, lock_sock = acquire_single_instance_lock()
    if not is_primary:
        # Υπάρχει ήδη ανοιχτή η εφαρμογή -- της στείλαμε σήμα να έρθει μπροστά,
        # τερματίζουμε αμέσως χωρίς να ανοίξουμε δεύτερο παράθυρο.
        sys.exit(0)
    root = tk.Tk()
    app = DownloaderApp(root, single_instance_sock=lock_sock)
    root.mainloop()
