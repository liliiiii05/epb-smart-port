# run_app.py
import os
import sys
import subprocess
import threading
import time
import webbrowser
import socket

def is_port_open(port):
    """Vérifie si le port est libre"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except:
            return False

def start_django():
    """Démarre le serveur Django"""
    # Désactiver l'affichage de la console
    startupinfo = None
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 6  # SW_MINIMIZE
    
    # Lancer le serveur
    process = subprocess.Popen(
        [sys.executable, 'manage.py', 'runserver', '8000'],
        startupinfo=startupinfo,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    )
    return process

def main():
    print("=" * 50)
    print("  🚢 EPB - PORT DE BÉJAÏA")
    print("  Gestion Portuaire")
    print("=" * 50)
    
    # Vérifier le port
    if not is_port_open(8000):
        print("⚠️ Un serveur tourne déjà")
        print("🌐 Ouverture du navigateur...")
        webbrowser.open('http://127.0.0.1:8000')
        input("Appuyez sur Entrée pour fermer...")
        return
    
    # Démarrer le serveur
    print("📡 Démarrage du serveur...")
    process = start_django()
    
    # Attendre que le serveur soit prêt
    time.sleep(3)
    
    # Ouvrir le navigateur
    print("🌐 Ouverture de l'application...")
    webbrowser.open('http://127.0.0.1:8000')
    
    print("\n✅ Application démarrée !")
    print("🔒 Fermez cette fenêtre pour arrêter le serveur\n")
    
    try:
        # Attendre l'arrêt
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
        print("\n👋 Serveur arrêté")

if __name__ == "__main__":
    main()