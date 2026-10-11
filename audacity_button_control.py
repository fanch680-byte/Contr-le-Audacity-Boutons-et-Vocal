import customtkinter as ctk
import os
import sys
import time

# Importation spécifique à Windows pour les pipes nommés
if sys.platform == 'win32':
    try:
        import win32file
        import win32pipe
    except ImportError:
        print("Erreur: La bibliothèque 'pywin32' est requise. Installez-la avec : pip install pywin32")
        sys.exit(1)

# Configuration de l'apparence
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class AudacityController:
    """Gère la communication avec Audacity via des pipes nommés (Windows)."""
    
    def __init__(self):
        self.to_handle = None
        self.from_handle = None
        self._connect()

    def _connect(self):
        """Établit la connexion aux pipes d'Audacity en utilisant pywin32."""
        if sys.platform != 'win32':
            raise ConnectionError("Ce script est conçu pour Windows uniquement.")

        try:
            self.to_handle = win32file.CreateFile(
                r'\\.\pipe\ToSrvPipe',
                win32file.GENERIC_WRITE,
                0, None,
                win32file.OPEN_EXISTING,
                0, None
            )
            self.from_handle = win32file.CreateFile(
                r'\\.\pipe\FromSrvPipe',
                win32file.GENERIC_READ,
                0, None,
                win32file.OPEN_EXISTING,
                0, None
            )
        except Exception as e:
            raise ConnectionError(
                f"Impossible de se connecter aux pipes d'Audacity.\n"
                f"Vérifiez qu'Audacity est lancé et que 'mod-script-pipe' est activé.\n"
                f"Détail de l'erreur : {e}"
            )

    def _drain_pipe(self):
        """Vide le pipe de lecture de toutes les données résiduelles en attente."""
        try:
            while True:
                _, bytes_avail, _ = win32pipe.PeekNamedPipe(self.from_handle, 0)
                if bytes_avail == 0:
                    break
                win32file.ReadFile(self.from_handle, min(bytes_avail, 4096))
        except Exception:
            pass

    def send_command(self, command, _retry=True):
        """Envoie une commande à Audacity et lit la réponse."""
        if not self.to_handle or not self.from_handle:
            return "Erreur: Non connecté à Audacity."
        
        self._drain_pipe()
        
        eol = '\r\n\0'
        full_command = (command + eol).encode('utf-8')
        
        try:
            win32file.WriteFile(self.to_handle, full_command)
        except Exception as e:
            if _retry:
                try:
                    self.close()
                    time.sleep(0.2)
                    self._connect()
                    return self.send_command(command, _retry=False)
                except Exception:
                    return "Erreur : impossible de se reconnecter à Audacity."
            return f"Erreur lors de l'envoi : {e}"
        
        result = ""
        try:
            while True:
                try:
                    _, data = win32file.ReadFile(self.from_handle, 4096)
                    if not data:
                        break
                    result += data.decode('utf-8', errors='ignore')
                    if result.endswith('\n'):
                        break
                except win32file.error as e:
                    if e.args[0] in (109, 232):
                        break
                    break
        except Exception:
            pass
        
        return result.strip()

    def close(self):
        """Ferme les handles des pipes."""
        try:
            if self.to_handle:
                win32file.CloseHandle(self.to_handle)
                self.to_handle = None
            if self.from_handle:
                win32file.CloseHandle(self.from_handle)
                self.from_handle = None
        except Exception:
            pass


class App(ctk.CTk):
    """Interface graphique principale avec boutons."""
    
    def __init__(self):
        super().__init__()
        self.title("Contrôle Audacity - Boutons")
        # Fenêtre plus compacte et redimensionnable
        self.geometry("900x700")
        self.minsize(900, 650)
        self.resizable(True, True)

        self.controller = None
        self.is_recording = False

        self._build_ui()
        self._initialize_backend()

    def _build_ui(self):
        # ========== TITRE + STATUT (compact) ==========
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(10, 5))
        
        self.label_title = ctk.CTkLabel(
            header_frame, text="🎚️ Contrôle Audacity", 
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.label_title.pack(side="left")

        self.label_status = ctk.CTkLabel(
            header_frame, text="Connexion...", 
            text_color="orange", font=ctk.CTkFont(size=12)
        )
        self.label_status.pack(side="right", padx=10)

        # ========== SECTION LECTURE ==========
        self._create_section("▶️  LECTURE", [
            ("▶  Lecture", self.cmd_play, "#2E8B57"),
            ("⏸  Pause", self.cmd_pause, "#B8860B"),
            ("⏹  Stop", self.cmd_stop, "#8B0000"),
        ])

        # ========== SECTION ENREGISTREMENT ==========
        self._create_section("⏺️  ENREGISTREMENT", [
            ("⏺  Enregistrer", self.cmd_record, "#8B0000"),
            ("⏹  Arrêter", self.cmd_stop_record, "#333333"),
        ])

        # ========== SECTION ÉDITION ==========
        self._create_section("✂️  ÉDITION", [
            ("Tout sélectionner", lambda: self.send_simple("SelectAll"), "#4B0082"),
            ("Copier", lambda: self.send_simple("Copy"), "#4B0082"),
            ("Coller", lambda: self.send_simple("Paste"), "#4B0082"),
            ("Couper", lambda: self.send_simple("Cut"), "#4B0082"),
            ("↶ Annuler", lambda: self.send_simple("Undo"), "#4B0082"),
            ("↷ Refaire", lambda: self.send_simple("Redo"), "#4B0082"),
        ])

        # ========== SECTION NAVIGATION ==========
        self._create_section("🎵  NAVIGATION", [
            ("⏪  -15s", lambda: self.send_simple("CursorLongJumpLeft"), "#1F4E79"),
            ("◀  -1s", lambda: self.send_simple("CursorShortJumpLeft"), "#1F4E79"),
            ("▶  +1s", lambda: self.send_simple("CursorShortJumpRight"), "#1F4E79"),
            ("⏩  +15s", lambda: self.send_simple("CursorLongJumpRight"), "#1F4E79"),
            ("⏮  Début", lambda: self.send_simple("CursTrackStart"), "#1F4E79"),
            ("⏭  Fin", lambda: self.send_simple("CursTrackEnd"), "#1F4E79"),
        ])

        # ========== SECTION ZOOM ==========
        self._create_section("🔍  ZOOM", [
            ("🔍  Zoom avant", lambda: self.send_simple("ZoomIn"), "#4A4A4A"),
            ("🔎  Zoom arrière", lambda: self.send_simple("ZoomOut"), "#4A4A4A"),
            ("🗑  Supprimer", lambda: self.send_simple("Delete"), "#4A4A4A"),
        ])

        # ========== SECTION FICHIERS ==========
        self._create_section("💾  FICHIERS", [
            ("💾  Sauvegarder projet", self.cmd_save_project, "#006400"),
            ("🎵  Exporter en MP3", self.cmd_export_mp3, "#006400"),
            ("❓  Aide", self.open_help, "#555555"),
        ])

        # ========== JOURNAL (agrandi + redimensionnable) ==========
        self.label_log = ctk.CTkLabel(
            self, text="📋 Journal des actions",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.label_log.pack(anchor="w", padx=20, pady=(8, 3))

        # Le journal s'étire pour prendre tout l'espace restant
        self.textbox_log = ctk.CTkTextbox(
            self, height=150, font=ctk.CTkFont(size=11)
        )
        self.textbox_log.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        self.textbox_log.insert("0.0", "En attente d'actions...\n")
        self.textbox_log.configure(state="disabled")

    def _create_section(self, title, buttons):
        """Crée une section de boutons avec un titre."""
        section_frame = ctk.CTkFrame(self, fg_color="transparent")
        section_frame.pack(fill="x", padx=15, pady=3)

        label = ctk.CTkLabel(
            section_frame, text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        )
        label.pack(anchor="w", padx=5, pady=(0, 2))

        buttons_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        buttons_frame.pack(fill="x")

        # Configuration des colonnes pour qu'elles s'étirent équitablement
        for col in range(5):
            buttons_frame.grid_columnconfigure(col, weight=1)

        for i, (text, command, color) in enumerate(buttons):
            btn = ctk.CTkButton(
                buttons_frame,
                text=text,
                command=command,
                height=34,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color=color,
                hover_color=self._lighten(color)
            )
            btn.grid(row=i // 5, column=i % 5, padx=3, pady=2, sticky="ew")

    def _lighten(self, hex_color):
        """Éclaircit légèrement une couleur pour l'effet hover."""
        try:
            hex_color = hex_color.lstrip('#')
            r = min(255, int(hex_color[0:2], 16) + 30)
            g = min(255, int(hex_color[2:4], 16) + 30)
            b = min(255, int(hex_color[4:6], 16) + 30)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return "#555555"

    def _initialize_backend(self):
        try:
            self.controller = AudacityController()
            self.label_status.configure(text="Connecté à Audacity ✓", text_color="green")
            self.log("Connexion réussie aux pipes d'Audacity.")
        except ConnectionError as e:
            self.label_status.configure(text="Erreur de connexion ✗", text_color="red")
            self.log(f"Erreur: {e}")

    # ============ LOG ============

    def log(self, message):
        """Ajoute un message au journal de l'interface."""
        self.textbox_log.configure(state="normal")
        self.textbox_log.insert("end", f"> {message}\n")
        self.textbox_log.see("end")
        self.textbox_log.configure(state="disabled")

    # ============ COMMANDES SIMPLES ============

    def send_simple(self, command, description=None):
        """Envoie une commande simple à Audacity."""
        if not self.controller:
            self.log("Erreur : non connecté à Audacity.")
            return
        
        label = description if description else command
        result = self.controller.send_command(command)
        
        if result and "n'a pas été reconnue" in result:
            self.log(f"❌ {label} → {result}")
        else:
            self.log(f"✓ {label}")

    # ============ LECTURE ============

    def cmd_play(self):
        self.send_simple("Play", "Lecture")

    def cmd_pause(self):
        self.send_simple("Pause", "Pause")

    def cmd_stop(self):
        self.send_simple("Stop", "Stop")

    # ============ ENREGISTREMENT ============

    def cmd_record(self):
        self.send_simple("Record1stChoice", "Enregistrer")
        self.is_recording = True

    def cmd_stop_record(self):
        self.send_simple("Stop", "Arrêter l'enregistrement")
        self.is_recording = False

    # ============ SAUVEGARDE ============

    def cmd_save_project(self):
        """Sauvegarde le projet dans un dossier Projets/."""
        if not self.controller:
            self.log("Erreur : non connecté à Audacity.")
            return
        
        project_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Projets")
        os.makedirs(project_dir, exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(project_dir, f"projet_{timestamp}.aup3")
        filepath_cmd = filepath.replace("\\", "/")
        
        command = f'SaveProject2: AddToHistory="0" Filename="{filepath_cmd}"'
        self.log(f"Sauvegarde du projet : {os.path.basename(filepath)}")
        result = self.controller.send_command(command)
        
        for _ in range(6):
            if os.path.exists(filepath):
                break
            time.sleep(0.5)
        
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            self.log(f"✓ Projet sauvegardé : {os.path.basename(filepath)} ({size // 1024} Ko)")
        else:
            self.log(f"⚠️ Échec de la sauvegarde : {result}")

    # ============ EXPORT MP3 ============

    def cmd_export_mp3(self):
        """Exporte l'audio en MP3 avec sélection automatique."""
        if not self.controller:
            self.log("Erreur : non connecté à Audacity.")
            return
        
        export_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Exports")
        os.makedirs(export_dir, exist_ok=True)
        
        self.log("Étape 1 : Sélection des pistes...")
        result = self.controller.send_command('SelectTracks: Mode="Set"')
        time.sleep(0.4)
        
        self.log("Étape 2 : Sélection de la plage de temps...")
        result = self.controller.send_command('SelectTime: Start=0 End=99999')
        time.sleep(0.4)
        
        self.controller.send_command("UnMuteAllTracks")
        time.sleep(0.2)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(export_dir, f"export_{timestamp}.mp3")
        filepath_cmd = filepath.replace("\\", "/")
        
        command = f'Export2: Filename="{filepath_cmd}" NumChannels=2'
        self.log(f"Étape 3 : Export MP3 : {os.path.basename(filepath)}")
        result = self.controller.send_command(command)
        
        actual_file = None
        if "Exported to" in result:
            try:
                actual_path = result.split("Exported to", 1)[1]
                actual_path = actual_path.split(":", 1)[1].strip()
                actual_file = actual_path.replace("/", "\\")
            except Exception:
                actual_file = None
        
        file_to_check = actual_file if actual_file else filepath
        
        for _ in range(6):
            if os.path.exists(file_to_check):
                break
            time.sleep(0.5)
        
        if os.path.exists(file_to_check):
            size = os.path.getsize(file_to_check)
            if size < 5000:
                self.log(f"⚠️ Fichier très petit ({size} octets) → probablement vide")
            else:
                self.log(f"✓ Fichier MP3 créé : {os.path.basename(file_to_check)} ({size // 1024} Ko)")
        else:
            self.log(f"⚠️ Échec de l'export : {result}")

    # ============ AIDE ============

    def open_help(self):
        """Ouvre le fichier d'aide dans le programme par défaut."""
        help_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                  "Aide_Controle_Boutons.txt")
        if os.path.exists(help_file):
            try:
                os.startfile(help_file)
                self.log("📖 Fichier d'aide ouvert.")
            except Exception as e:
                self.log(f"Erreur lors de l'ouverture de l'aide : {e}")
        else:
            self.log("⚠️ Fichier d'aide introuvable.")
            self.log("   Assurez-vous que 'Aide_Controle_Boutons.txt' est dans le même dossier que le script.")

    # ============ FERMETURE ============

    def on_closing(self):
        if self.controller:
            self.controller.close()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()