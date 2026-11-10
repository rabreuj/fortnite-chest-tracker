from PIL import Image

# Abre tu imagen actual
img = Image.open("pirate-shop-token.png")

# Guárdala como .ico con los tamaños estándar de Windows
img.save("icono_app.ico", format="ICO", sizes=[(32, 32), (64, 64)])
print("¡Icono creado con éxito!")