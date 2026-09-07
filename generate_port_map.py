import matplotlib.pyplot as plt
import matplotlib.patches as patches

# Dimensions de l'image (en unités arbitraires)
width, height = 1200, 800

fig, ax = plt.subplots(figsize=(width/100, height/100), dpi=100)
ax.set_xlim(0, width)
ax.set_ylim(0, height)
ax.set_facecolor('#e6f0fa')  # bleu clair pour l'eau
ax.set_title("Plan schématique du port de Béjaïa", fontsize=14)
ax.set_xlabel("X (mètres relatifs)")
ax.set_ylabel("Y (mètres relatifs)")

# Définition des quais (x, y, largeur, hauteur, couleur)
quais = [
    {"nom": "Quai 1", "x": 50, "y": 700, "w": 150, "h": 20, "couleur": "#8B4513"},
    {"nom": "Quai 2", "x": 220, "y": 700, "w": 150, "h": 20, "couleur": "#8B4513"},
    {"nom": "Quai 3", "x": 390, "y": 700, "w": 150, "h": 20, "couleur": "#8B4513"},
    {"nom": "Quai 4", "x": 560, "y": 680, "w": 120, "h": 20, "couleur": "#A0522D"},
    {"nom": "Quai 5", "x": 700, "y": 680, "w": 120, "h": 20, "couleur": "#A0522D"},
    {"nom": "Quai 8", "x": 100, "y": 600, "w": 200, "h": 20, "couleur": "#CD853F"},
    {"nom": "Quai 11", "x": 320, "y": 580, "w": 180, "h": 20, "couleur": "#CD853F"},
    {"nom": "Quai 12", "x": 520, "y": 560, "w": 180, "h": 20, "couleur": "#CD853F"},
    {"nom": "Quai 13", "x": 720, "y": 540, "w": 180, "h": 20, "couleur": "#CD853F"},
    {"nom": "Quai 14", "x": 920, "y": 520, "w": 150, "h": 20, "couleur": "#CD853F"},
    {"nom": "Quai 15", "x": 50, "y": 500, "w": 140, "h": 20, "couleur": "#CD853F"},
    {"nom": "Quai 16", "x": 210, "y": 500, "w": 140, "h": 20, "couleur": "#CD853F"},
    {"nom": "Quai 17", "x": 370, "y": 480, "w": 160, "h": 20, "couleur": "#CD853F"},
    {"nom": "Quai 18", "x": 550, "y": 480, "w": 160, "h": 20, "couleur": "#CD853F"},
    {"nom": "Quai 19", "x": 730, "y": 460, "w": 140, "h": 20, "couleur": "#FFD700"},
    {"nom": "Quai 21", "x": 50, "y": 300, "w": 220, "h": 30, "couleur": "#2E8B57"},
    {"nom": "Quai 22", "x": 290, "y": 300, "w": 220, "h": 30, "couleur": "#2E8B57"},
    {"nom": "Quai 23", "x": 530, "y": 300, "w": 220, "h": 30, "couleur": "#2E8B57"},
    {"nom": "Quai 24", "x": 770, "y": 300, "w": 180, "h": 30, "couleur": "#4682B4"},
    {"nom": "Quai 25", "x": 970, "y": 280, "w": 100, "h": 20, "couleur": "#D2691E"},
    {"nom": "Quai 26", "x": 50, "y": 100, "w": 500, "h": 40, "couleur": "#A9A9A9"},
]

# Dessiner les rectangles des quais
for q in quais:
    rect = patches.Rectangle((q["x"], q["y"]), q["w"], q["h"],
                             linewidth=1, edgecolor='black', facecolor=q["couleur"])
    ax.add_patch(rect)
    # Ajouter le nom du quai au centre
    cx = q["x"] + q["w"]/2
    cy = q["y"] + q["h"]/2
    ax.text(cx, cy, q["nom"], ha='center', va='center', fontsize=8, color='white', weight='bold')

# Sauvegarder l'image
plt.savefig("plan_port_bejaia.png", dpi=100, bbox_inches='tight')
print("✅ Image générée : plan_port_bejaia.png")