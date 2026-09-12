from PIL import Image

def convert_png_to_ico():
    # Φορτώνει την εικόνα που αποθήκευσες στον φάκελο
    img = Image.open("ai_icon.png")
    
    # Τη σώζει ως 'icon.ico' με όλα τα μεγέθη (256x256 έως 16x16)
    img.save(
        "icon.ico", 
        format="ICO", 
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    )
    print("✨ Το icon.ico αντικαταστάθηκε με επιτυχία!")

if __name__ == "__main__":
    convert_png_to_ico()