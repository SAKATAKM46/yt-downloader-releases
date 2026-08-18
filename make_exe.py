import os
import shutil
import subprocess

print("🔪 Σκοτώνουμε τυχόν κολλημένες διεργασίες του .exe στο background...")
subprocess.run(["taskkill", "/f", "/im", "YouTubeDownloader-v1.0.3.exe"], capture_output=True)

print("🧹 Καθάρισμα παλιών φακέλων (build, dist)...")
shutil.rmtree("build", ignore_errors=True)
shutil.rmtree("dist", ignore_errors=True)
if os.path.exists("YouTubeDownloader-v1.0.3.spec"):
    os.remove("YouTubeDownloader-v1.0.3.spec")

# ΣΗΜΑΝΤΙΚΟ: Το 'bin' folder (yt-dlp.exe, ffmpeg.exe) ΔΕΝ πακετάρεται πια μέσα στο .exe
# (αφαιρέθηκε το --add-data "bin;bin"). Μένει ΕΞΩΤΕΡΙΚΟ, δίπλα στο .exe, ώστε η
# αυτο-ενημέρωση του yt-dlp (yt-dlp.exe -U) να είναι μόνιμη και να μη χάνεται
# κάθε φορά που κλείνει το πρόγραμμα.
command = [
    "pyinstaller",
    "--noconsole",
    "--onefile",
    "--collect-all", "tkinter",
    "--add-data", "icon.ico;.",
    "YouTubeDownloader-v1.0.3.py"
]

print("🚀 Χτίζουμε το τελικό .exe... Παρακαλώ περιμένετε...\n")
subprocess.run(command)

print("\n📦 Αντιγραφή του φακέλου 'bin' δίπλα στο τελικό .exe (dist/)...")
dist_bin = os.path.join("dist", "bin")
if os.path.exists(dist_bin):
    shutil.rmtree(dist_bin)
shutil.copytree("bin", dist_bin)

print("\n✅ ΟΛΟΚΛΗΡΩΘΗΚΕ ΚΑΘΑΡΑ!")
print("👉 Πήγαινε στο φάκελο 'dist' — θα βρεις το .exe ΚΑΙ τον φάκελο 'bin' δίπλα του.")
print("👉 Μετέφερε ΚΑΙ τα δύο μαζί (exe + bin) αν αντιγράψεις το πρόγραμμα αλλού (π.χ. USB stick).")
