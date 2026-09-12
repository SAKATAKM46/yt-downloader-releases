import os
import shutil
import subprocess

APP_NAME = "YouTubeDownloader-v2.2.2"
APP_SOURCE = "YouTubeDownloader-v2.2.2.py"
APP_EXE = APP_NAME + ".exe"

print(f"🔪 Σκοτώνουμε τυχόν κολλημένες διεργασίες του {APP_EXE} στο background...")
subprocess.run(["taskkill", "/f", "/im", APP_EXE], capture_output=True)

print("🧹 Καθάρισμα παλιών φακέλων (build, dist)...")
shutil.rmtree("build", ignore_errors=True)
shutil.rmtree("dist", ignore_errors=True)
spec_file = APP_NAME + ".spec"
if os.path.exists(spec_file):
    os.remove(spec_file)

# ΣΗΜΑΝΤΙΚΟ: Το 'bin' folder (yt-dlp.exe, ffmpeg.exe) ΔΕΝ πακετάρεται πια μέσα στο .exe
# (αφαιρέθηκε το --add-data "bin;bin"). Μένει ΕΞΩΤΕΡΙΚΟ, δίπλα στο .exe, ώστε η
# αυτο-ενημέρωση του yt-dlp (yt-dlp.exe -U) να είναι μόνιμη και να μη χάνεται
# κάθε φορά που κλείνει το πρόγραμμα.
#
# ΝΕΟ (v2.0.0): προστέθηκαν Pillow (εξώφυλλα) και pygame (αναπαραγωγή ήχου) —
# χρειάζονται --collect-all ώστε το PyInstaller να πάρει μαζί τους όλα τα
# binaries/data τους (SDL κ.λπ.). Τρέξε πρώτα: pip install -r requirements.txt
command = [
    "pyinstaller",
    "--noconsole",
    "--onedir",
    "--icon", "icon.ico",       # ΝΕΟ: εικονίδιο στο ίδιο το .exe (Explorer/taskbar/Start
                                 # Menu) -- πριν έλειπε, το iconbitmap() μέσα στην εφαρμογή
                                 # βάζει εικονίδιο μόνο στο παράθυρο ΑΦΟΥ ήδη ανοίξει.
    "--collect-all", "tkinter",
    "--collect-all", "PIL",
    "--collect-all", "pygame",
    "--add-data", "icon.ico;.",
    APP_SOURCE
]

print("🚀 Χτίζουμε το τελικό .exe... Παρακαλώ περιμένετε...\n")
result = subprocess.run(command)

# ΣΗΜΑΝΤΙΚΟ: πριν προχωρήσουμε παρακάτω (αντιγραφή bin/, μήνυμα επιτυχίας), πρέπει να
# ελέγξουμε ΠΡΑΓΜΑΤΙΚΑ αν το PyInstaller πέτυχε -- τόσο το return code ΟΣΟ ΚΑΙ αν
# όντως δημιουργήθηκε το .exe μέσα στο dist/. Παλιότερα το script συνέχιζε τυφλά και
# τύπωνε "ΟΛΟΚΛΗΡΩΘΗΚΕ ΚΑΘΑΡΑ" ακόμα και όταν το PyInstaller απέτυχε εντελώς (π.χ. λόγω
# χαλασμένου/μετακινημένου .venv), κάτι που μπέρδευε αντί να βοηθάει.
#
# ΠΡΟΣΟΧΗ: με --onedir (αντί για --onefile) το PyInstaller βάζει το .exe ΜΕΣΑ σε δικό
# του υποφάκελο -- dist/<APP_NAME>/<APP_NAME>.exe -- ΟΧΙ απευθείας dist/<APP_NAME>.exe.
# Αυτός ο υποφάκελος (onedir_root) είναι ΚΑΙ το σημείο όπου πρέπει να μπει ο φάκελος
# 'bin', γιατί η εφαρμογή ψάχνει το bin/ ΔΙΠΛΑ στο πραγματικό .exe (βλ. get_base_dir()
# στον πηγαίο κώδικα: os.path.dirname(sys.executable)).
onedir_root = os.path.join("dist", APP_NAME)
dist_exe = os.path.join(onedir_root, APP_EXE)
if result.returncode != 0 or not os.path.isfile(dist_exe):
    print("\n❌ ΑΠΕΤΥΧΕ το χτίσιμο του .exe -- το PyInstaller δεν ολοκληρώθηκε σωστά.")
    print(f"   (return code: {result.returncode}, βρέθηκε αρχείο: {os.path.isfile(dist_exe)})")
    print("\nΠιθανότερη αιτία: χαλασμένο ή 'μετακινημένο' virtual environment (.venv).")
    print("Τα .venv ΔΕΝ αντέχουν να μετακινηθεί/μετονομαστεί/αντιγραφεί ο φάκελος του project")
    print("μετά τη δημιουργία τους -- τα εργαλεία μέσα στο Scripts\\ (pip.exe, pyinstaller.exe)")
    print("θυμούνται τη ΠΑΛΙΑ απόλυτη διαδρομή και σταματούν να δουλεύουν.")
    print("\nΛύση:")
    print("  1. Διάλεξε τον ΤΕΛΙΚΟ φάκελο όπου θα μείνει μόνιμα το project.")
    print("  2. Διέγραψε τον παλιό φάκελο .venv μέσα σε αυτόν.")
    print("  3. Άνοιξε τερματικό ΑΚΡΙΒΩΣ μέσα σε αυτόν τον φάκελο και τρέξε:")
    print("       python -m venv .venv")
    print("       .venv\\Scripts\\activate")
    print("       pip install -r requirements.txt")
    print("       python make_exe.py")
    raise SystemExit(1)

print(f"\n📦 Αντιγραφή του φακέλου 'bin' δίπλα στο τελικό .exe ({onedir_root})...")
dist_bin = os.path.join(onedir_root, "bin")
if os.path.exists(dist_bin):
    shutil.rmtree(dist_bin)
shutil.copytree("bin", dist_bin)

print("\n✅ ΟΛΟΚΛΗΡΩΘΗΚΕ ΚΑΘΑΡΑ!")
print(f"👉 Πήγαινε στο φάκελο '{onedir_root}' — εκεί θα βρεις το .exe ΚΑΙ τον φάκελο 'bin' δίπλα του,")
print("   μαζί με όλα τα υπόλοιπα αρχεία που χρειάζεται το πρόγραμμα για να τρέξει.")
print(f"👉 Για φορητή έκδοση: πάρε ΟΛΟΚΛΗΡΟ τον φάκελο '{APP_NAME}' (όχι μόνο το .exe) όπου θες")
print("   (π.χ. USB stick) — όλα τα αρχεία μέσα του είναι απαραίτητα μαζί.")
