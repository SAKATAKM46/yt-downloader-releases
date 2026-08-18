from PIL import Image, ImageDraw, ImageFont
import os

def create_mp3_icon():
    # Δημιουργούμε μια εικόνα υψηλής ανάλυσης (256x256) για να βγει πεντακάθαρο 3D
    size = (256, 256)
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 1. Σχεδιάζουμε ένα στρογγυλεμένο κουτί για 3D αίσθηση (φόντο)
    # Κάνουμε μια σκιά από κάτω για το 3D εφέ
    draw.rounded_rectangle([15, 25, 241, 241], radius=40, fill=(20, 30, 20, 180))
    # Το κύριο πράσινο κουτί
    draw.rounded_rectangle([10, 15, 236, 231], radius=40, fill=(46, 204, 113))
    
    # 2. Προσθέτουμε μια ελαφριά φωτεινή γραμμή πάνω-πάνω για γυαλάδα/3D
    draw.rounded_rectangle([15, 20, 231, 60], radius=25, fill=(88, 214, 141, 150))
    
    # 3. Σχεδιάζουμε το μαύρο βελάκι που δείχνει κάτω (Download)
    # Βελάκι (γραμμή και κεφάλι βέλους)
    arrow_color = (20, 20, 20)
    # Κορμός βέλους
    draw.rectangle([112, 65, 144, 135], fill=arrow_color)
    # Τριγωνική μύτη βέλους
    draw.polygon([(80, 135), (176, 135), (128, 185)], fill=arrow_color)
    
    # 4. Γράφουμε το "MP3" στο κάτω μέρος
    try:
        # Δοκιμάζουμε να βρούμε μια ωραία χοντρή γραμματοσειρά στα Windows
        font = ImageFont.truetype("arialbd.ttf", 42)
    except IOError:
        # Αν δεν τη βρει, παίρνει την προεπιλεγμένη
        font = ImageFont.load_default()
        
    # Κάνουμε μια σκιά στο κείμενο για 3D εφέ
    draw.text((72, 192), "MP3", fill=(20, 20, 20), font=font)
    # Το κυρίως λευκό/ανοιχτό κείμενο επάνω στη σκιά
    draw.text((70, 190), "MP3", fill=(255, 255, 255), font=font)
    
    # Αποθήκευση σε ICO με πολλαπλά μεγέθη για να φαίνεται τέλειο παντού (Taskbar, USB, Desktop)
    icon_path = "icon.ico"
    image.save(
        icon_path, 
        format="ICO", 
        sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)]
    )
    print(f"Το εικονίδιο '{icon_path}' μόλις δημιουργήθηκε με επιτυχία! 🎨")

if __name__ == "__main__":
    create_mp3_icon()