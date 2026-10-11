import customtkinter as ctk
import os
import sys
import time
import threading

# Importation spécifique à Windows pour les pipes nommés
if sys.platform == 'win32':
    try:
        import win32file
        import win32pipe
    except ImportError:
        print("Erreur: La bibliothèque 'pywin32' est requise. Installez-la avec : pip install pywin32")
        sys.exit(1)

# Importation optionnelle pour le mode vocal
VOICE_AVAILABLE = False
try:
    import speech_recognition as sr
    import pyttsx3
    VOICE_AVAILABLE = True
except ImportError:
    print("Info: Les bibliothèques vocales ne sont pas installées.")

# Configuration de l'apparence
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# ============================================================
#  GESTION DES CHEMINS (SCRIPT + EXE)
# ============================================================

def get_base_path():
    """Retourne le dossier de base pour les fichiers créés (Exports, Projets).
    - En mode script : dossier du .py
    - En mode exe : dossier de l'exe
    """
    if getattr(sys, 'frozen', False):
        # Mode exe (PyInstaller)
        return os.path.dirname(sys.executable)
    else:
        # Mode script Python
        return os.path.dirname(os.path.abspath(__file__))


def get_resource_path(relative_path):
    """Retourne le chemin d'une ressource embarquée (fichiers d'aide, icônes).
    - En mode exe : extrait dans _MEIPASS (dossier temporaire)
    - En mode script : dans le dossier du .py
    """
    if getattr(sys, 'frozen', False):
        # Mode exe : les données sont extraites dans _MEIPASS
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        # Mode script
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


# ============================================================
#  CONTRÔLEUR AUDACITY
# ============================================================

class AudacityController:
    """Gère la communication avec Audacity via des pipes nommés (Windows)."""
    
    def __init__(self):
        self.to_handle = None
        self.from_handle = None
        self._connect()

    def _connect(self):
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
        try:
            while True:
                _, bytes_avail, _ = win32pipe.PeekNamedPipe(self.from_handle, 0)
                if bytes_avail == 0:
                    break
                win32file.ReadFile(self.from_handle, min(bytes_avail, 4096))
        except Exception:
            pass

    def send_command(self, command, _retry=True):
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
        try:
            if self.to_handle:
                win32file.CloseHandle(self.to_handle)
                self.to_handle = None
            if self.from_handle:
                win32file.CloseHandle(self.from_handle)
                self.from_handle = None
        except Exception:
            pass


# ============================================================
#  MOTEUR VOCAL
# ============================================================

class VoiceCommandEngine:
    """Moteur de reconnaissance vocale et de mappage des commandes."""
    
    def __init__(self, controller):
        self.recognizer = sr.Recognizer()
        self.controller = controller
        
        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', 180)
            self.engine.setProperty('volume', 0.9)
        except Exception:
            self.engine = None
        
        self.command_map = {
            "play": "Play", "jouer": "Play", "joue": "Play", "lance": "Play",
            "lancer": "Play", "lecture": "Play", "démarre": "Play",
            "démarrer": "Play", "démarrage": "Play", "écoute": "Play",
            "écouter": "Play", "reprendre": "Play", "reprise": "Play",
            "stop": "Stop", "arrêter": "Stop", "arrête": "Stop", "arrêt": "Stop",
            "stoppe": "Stop", "fin": "Stop", "terminer": "Stop", "termine": "Stop",
            "enregistrer": "Record1stChoice", "enregistre": "Record1stChoice",
            "enregistrement": "Record1stChoice", "record": "Record1stChoice",
            "capture": "Record1stChoice", "capturer": "Record1stChoice",
            "micro": "Record1stChoice",
            "pause": "Pause", "mettre en pause": "Pause",
            "suspendre": "Pause", "suspend": "Pause",
            "nouveau projet": "New", "nouveau": "New", "new project": "New",
            "new": "New", "créer projet": "New", "créer": "New",
            "annuler": "Undo", "undo": "Undo", "annule": "Undo",
            "retour arrière": "Undo",
            "refaire": "Redo", "redo": "Redo", "refais": "Redo", "rétablir": "Redo",
            "couper": "Cut", "cut": "Cut",
            "copier": "Copy", "copy": "Copy",
            "coller": "Paste", "paste": "Paste",
            "sélectionner tout": "SelectAll", "tout sélectionner": "SelectAll",
            "select all": "SelectAll", "tout": "SelectAll",
            "avancer": "CursorShortJumpRight", "avance": "CursorShortJumpRight",
            "reculer": "CursorShortJumpLeft", "recule": "CursorShortJumpLeft",
            "grand saut avant": "CursorLongJumpRight",
            "grand saut arrière": "CursorLongJumpLeft",
            "début": "CursTrackStart", "commencement": "CursTrackStart",
            "fin de piste": "CursTrackEnd",
            "supprimer": "Delete", "effacer": "Delete", "silence": "Silence",
            "zoom avant": "ZoomIn", "zoom arrière": "ZoomOut",
            "agrandir": "ZoomIn", "réduire": "ZoomOut",
        }
        
        self.export_keywords = ["exporter", "exporte", "export", "export audio", "exporter audio", "mp3"]
        self.save_keywords = ["sauvegarder", "sauvegarde", "sauver", "save project", "enregistrer projet"]

    def speak(self, text):
        if self.engine:
            try:
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception:
                pass

    def save_project(self, callback):
        project_dir = os.path.join(get_base_path(), "Projets")
        os.makedirs(project_dir, exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(project_dir, f"projet_{timestamp}.aup3")
        filepath_cmd = filepath.replace("\\", "/")
        
        command = f'SaveProject2: AddToHistory="0" Filename="{filepath_cmd}"'
        callback(f"Sauvegarde du projet : {os.path.basename(filepath)}")
        result = self.controller.send_command(command)
        
        for _ in range(6):
            if os.path.exists(filepath):
                break
            time.sleep(0.5)
        
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            callback(f"✓ Projet sauvegardé : {os.path.basename(filepath)} ({size // 1024} Ko)")
            self.speak("Projet sauvegardé.")
        else:
            callback(f"⚠️ Échec de la sauvegarde : {result}")
            self.speak("Erreur lors de la sauvegarde.")

    def export_audio_mp3(self, callback):
        export_dir = os.path.join(get_base_path(), "Exports")
        os.makedirs(export_dir, exist_ok=True)
        
        callback("Étape 1 : Sélection des pistes...")
        self.controller.send_command('SelectTracks: Mode="Set"')
        time.sleep(0.4)
        
        callback("Étape 2 : Sélection de la plage de temps...")
        self.controller.send_command('SelectTime: Start=0 End=99999')
        time.sleep(0.4)
        
        self.controller.send_command("UnMuteAllTracks")
        time.sleep(0.2)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(export_dir, f"export_{timestamp}.mp3")
        filepath_cmd = filepath.replace("\\", "/")
        
        command = f'Export2: Filename="{filepath_cmd}" NumChannels=2'
        callback(f"Étape 3 : Export MP3 : {os.path.basename(filepath)}")
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
                callback(f"⚠️ Fichier très petit ({size} octets) → probablement vide")
            else:
                callback(f"✓ Fichier MP3 créé : {os.path.basename(file_to_check)} ({size // 1024} Ko)")
                self.speak("Export MP3 effectué.")
        else:
            callback(f"⚠️ Échec de l'export : {result}")

    def listen_and_execute(self, callback):
        with sr.Microphone() as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
            self.recognizer.energy_threshold = 300
            self.recognizer.dynamic_energy_threshold = True
            self.recognizer.pause_threshold = 0.8
            
            callback("🎧 Écoute en cours... Parlez maintenant.")
            try:
                audio = self.recognizer.listen(source, timeout=7, phrase_time_limit=5)
                callback("Analyse de la commande...")
                text = self.recognizer.recognize_google(audio, language="fr-FR").lower()
                callback(f"Reconnu : « {text} »")
                
                for keyword in self.export_keywords:
                    if keyword in text:
                        self.export_audio_mp3(callback)
                        return
                
                for keyword in self.save_keywords:
                    if keyword in text:
                        self.save_project(callback)
                        return
                
                for key_phrase, audacity_cmd in self.command_map.items():
                    if key_phrase in text:
                        callback(f"Envoi de '{audacity_cmd}' à Audacity...")
                        result = self.controller.send_command(audacity_cmd)
                        self.speak(f"Commande {audacity_cmd} exécutée.")
                        callback(f"Réponse d'Audacity : {result}")
                        return
                
                self.speak("Commande non reconnue.")
                callback("❌ Commande non reconnue.")
                
            except sr.UnknownValueError:
                callback("❌ Impossible de comprendre l'audio. Réessayez.")
            except sr.RequestError as e:
                callback(f"❌ Erreur de service Google : {e}")
            except sr.WaitTimeoutError:
                callback("⚠️ Aucune parole détectée dans le délai imparti.")
            except Exception as e:
                callback(f"❌ Erreur : {e}")


# ============================================================
#  APPLICATION PRINCIPALE
# ============================================================

class App(ctk.CTk):
    """Interface unifiée : boutons + vocal dans des onglets."""
    
    def __init__(self):
        super().__init__()
        self.title("Contrôle Audacity - Boutons + Vocal")
        self.geometry("950x850")
        self.minsize(900, 750)
        self.resizable(True, True)

        self.controller = None
        self.voice_engine = None
        self.is_listening = False
        self.is_recording = False

        self._build_ui()
        self._initialize_backend()

    def _build_ui(self):
        # ========== HEADER COMMUN ==========
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(12, 5))
        
        self.label_title = ctk.CTkLabel(
            header_frame, text="🎚️ Contrôle Audacity", 
            font=ctk.CTkFont(size=22, weight="bold")
        )
        self.label_title.pack(side="left")

        self.label_status = ctk.CTkLabel(
            header_frame, text="Connexion...", 
            text_color="orange", font=ctk.CTkFont(size=12)
        )
        self.label_status.pack(side="right", padx=10)

        # ========== ONGLETS ==========
        self.tabview = ctk.CTkTabview(self, height=560)
        self.tabview.pack(fill="x", padx=20, pady=(5, 5))
        
        self.tabview.add("🎚️ Boutons")
        self.tabview.add("🎙️ Vocal")
        
        self.tab_buttons = self.tabview.tab("🎚️ Boutons")
        self.tab_voice = self.tabview.tab("🎙️ Vocal")
        
        self._build_buttons_tab()
        self._build_voice_tab()

        # ========== JOURNAL COMMUN ==========
        self.label_log = ctk.CTkLabel(
            self, text="📋 Journal des actions",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.label_log.pack(anchor="w", padx=20, pady=(8, 3))

        self.textbox_log = ctk.CTkTextbox(
            self, height=140, font=ctk.CTkFont(size=11)
        )
        self.textbox_log.pack(fill="both", expand=True, padx=20, pady=(0, 15))
        self.textbox_log.insert("0.0", "En attente d'actions...\n")
        self.textbox_log.configure(state="disabled")

    def _build_buttons_tab(self):
        self.tab_buttons.grid_columnconfigure(0, weight=1)

        self._create_button_section(self.tab_buttons, "▶️  LECTURE", [
            ("▶  Lecture", self.cmd_play, "#2E8B57"),
            ("⏸  Pause", self.cmd_pause, "#B8860B"),
            ("⏹  Stop", self.cmd_stop, "#8B0000"),
        ], row=0)

        self._create_button_section(self.tab_buttons, "⏺️  ENREGISTREMENT", [
            ("⏺  Enregistrer", self.cmd_record, "#8B0000"),
            ("⏹  Arrêter", self.cmd_stop_record, "#333333"),
        ], row=1)

        self._create_button_section(self.tab_buttons, "✂️  ÉDITION", [
            ("Tout sélectionner", lambda: self.send_simple("SelectAll"), "#4B0082"),
            ("Copier", lambda: self.send_simple("Copy"), "#4B0082"),
            ("Coller", lambda: self.send_simple("Paste"), "#4B0082"),
            ("Couper", lambda: self.send_simple("Cut"), "#4B0082"),
            ("↶ Annuler", lambda: self.send_simple("Undo"), "#4B0082"),
            ("↷ Refaire", lambda: self.send_simple("Redo"), "#4B0082"),
        ], row=2)

        self._create_button_section(self.tab_buttons, "🎵  NAVIGATION", [
            ("⏪  -15s", lambda: self.send_simple("CursorLongJumpLeft"), "#1F4E79"),
            ("◀  -1s", lambda: self.send_simple("CursorShortJumpLeft"), "#1F4E79"),
            ("▶  +1s", lambda: self.send_simple("CursorShortJumpRight"), "#1F4E79"),
            ("⏩  +15s", lambda: self.send_simple("CursorLongJumpRight"), "#1F4E79"),
            ("⏮  Début", lambda: self.send_simple("CursTrackStart"), "#1F4E79"),
            ("⏭  Fin", lambda: self.send_simple("CursTrackEnd"), "#1F4E79"),
        ], row=3)

        self._create_button_section(self.tab_buttons, "🔍  ZOOM", [
            ("🔍  Zoom avant", lambda: self.send_simple("ZoomIn"), "#4A4A4A"),
            ("🔎  Zoom arrière", lambda: self.send_simple("ZoomOut"), "#4A4A4A"),
            ("🗑  Supprimer", lambda: self.send_simple("Delete"), "#4A4A4A"),
        ], row=4)

        self._create_button_section(self.tab_buttons, "💾  FICHIERS", [
            ("💾  Sauvegarder projet", self.cmd_save_project, "#006400"),
            ("🎵  Exporter en MP3", self.cmd_export_mp3, "#006400"),
            ("❓  Aide boutons", self.open_help_buttons, "#555555"),
        ], row=5)

    def _create_button_section(self, parent, title, buttons, row):
        section_frame = ctk.CTkFrame(parent, fg_color="transparent")
        section_frame.grid(row=row, column=0, sticky="ew", padx=5, pady=3)
        
        label = ctk.CTkLabel(
            section_frame, text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        )
        label.pack(anchor="w", padx=5, pady=(0, 2))

        buttons_frame = ctk.CTkFrame(section_frame, fg_color="transparent")
        buttons_frame.pack(fill="x")

        for col in range(6):
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
            btn.grid(row=i // 6, column=i % 6, padx=3, pady=2, sticky="ew")

    def _build_voice_tab(self):
        self.tab_voice.grid_columnconfigure(0, weight=1)

        if not VOICE_AVAILABLE:
            warning = ctk.CTkLabel(
                self.tab_voice,
                text="⚠️ Les bibliothèques vocales ne sont pas installées.\n\n"
                     "Pour activer le mode vocal, ouvrez un terminal et exécutez :\n\n"
                     "    pip install SpeechRecognition pyaudio pyttsx3\n\n"
                     "Puis relancez l'application.",
                font=ctk.CTkFont(size=13),
                text_color="#FF8888",
                justify="center"
            )
            warning.pack(pady=60, padx=20)
            return

        self.button_listen = ctk.CTkButton(
            self.tab_voice,
            text="🎤 Écouter une commande",
            command=self.toggle_listening,
            width=400, height=55,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#2E8B57",
            hover_color="#3EA067"
        )
        self.button_listen.pack(pady=(30, 15))

        self.label_voice_info = ctk.CTkLabel(
            self.tab_voice,
            text="Cliquez sur le bouton, puis prononcez votre commande.",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.label_voice_info.pack(pady=5)

        info_frame = ctk.CTkFrame(self.tab_voice, fg_color="#2B2B2B")
        info_frame.pack(fill="x", padx=20, pady=(20, 10))

        title = ctk.CTkLabel(
            info_frame, text="📖 Quelques exemples de commandes vocales",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        title.pack(anchor="w", padx=15, pady=(10, 5))

        commands_text = (
            "▶  Lecture / Jouer / Lance       ⏹  Stop / Arrête / Fin\n"
            "⏸  Pause / Suspendre              ⏺  Enregistrer / Micro\n"
            "✂  Copier / Coller / Couper       ↶  Annuler / Refaire\n"
            "🎵  Avancer / Reculer              💾  Sauvegarder / Exporter"
        )
        
        commands_label = ctk.CTkLabel(
            info_frame,
            text=commands_text,
            font=ctk.CTkFont(size=11),
            justify="left",
            text_color="#CCCCCC"
        )
        commands_label.pack(anchor="w", padx=15, pady=(5, 15))

        self.button_help_voice = ctk.CTkButton(
            self.tab_voice,
            text="❓ Aide du mode vocal",
            command=self.open_help_voice,
            width=250, height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#555555",
            hover_color="#777777"
        )
        self.button_help_voice.pack(pady=(15, 10))

    def _lighten(self, hex_color):
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
            if VOICE_AVAILABLE:
                self.voice_engine = VoiceCommandEngine(self.controller)
            self.label_status.configure(text="Connecté à Audacity ✓", text_color="green")
            self.log("Connexion réussie aux pipes d'Audacity.")
            if VOICE_AVAILABLE:
                self.log("Mode vocal disponible.")
            else:
                self.log("Mode vocal indisponible (bibliothèques manquantes).")
        except ConnectionError as e:
            self.label_status.configure(text="Erreur de connexion ✗", text_color="red")
            self.log(f"Erreur: {e}")

    def log(self, message):
        self.textbox_log.configure(state="normal")
        self.textbox_log.insert("end", f"> {message}\n")
        self.textbox_log.see("end")
        self.textbox_log.configure(state="disabled")

    def send_simple(self, command, description=None):
        if not self.controller:
            self.log("❌ Erreur : non connecté à Audacity.")
            return
        
        label = description if description else command
        result = self.controller.send_command(command)
        
        if result and "n'a pas été reconnue" in result:
            self.log(f"❌ {label} → {result}")
        else:
            self.log(f"✓ {label}")

    def cmd_play(self):
        self.send_simple("Play", "Lecture")

    def cmd_pause(self):
        self.send_simple("Pause", "Pause")

    def cmd_stop(self):
        self.send_simple("Stop", "Stop")

    def cmd_record(self):
        self.send_simple("Record1stChoice", "Enregistrer")
        self.is_recording = True

    def cmd_stop_record(self):
        self.send_simple("Stop", "Arrêter l'enregistrement")
        self.is_recording = False

    def cmd_save_project(self):
        if not self.controller:
            self.log("❌ Erreur : non connecté à Audacity.")
            return
        
        project_dir = os.path.join(get_base_path(), "Projets")
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

    def cmd_export_mp3(self):
        if not self.controller:
            self.log("❌ Erreur : non connecté à Audacity.")
            return
        
        export_dir = os.path.join(get_base_path(), "Exports")
        os.makedirs(export_dir, exist_ok=True)
        
        self.log("Étape 1 : Sélection des pistes...")
        self.controller.send_command('SelectTracks: Mode="Set"')
        time.sleep(0.4)
        
        self.log("Étape 2 : Sélection de la plage de temps...")
        self.controller.send_command('SelectTime: Start=0 End=99999')
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

    def toggle_listening(self):
        if not VOICE_AVAILABLE:
            self.log("⚠️ Mode vocal indisponible.")
            return
        
        if not self.voice_engine:
            self.log("❌ Moteur vocal non initialisé.")
            return

        if self.is_listening:
            self.is_listening = False
            self.button_listen.configure(
                text="🎤 Écouter une commande",
                fg_color="#2E8B57",
                hover_color="#3EA067"
            )
            self.log("Arrêt de l'écoute.")
            return

        self.is_listening = True
        self.button_listen.configure(
            text="⏹️ Arrêter l'écoute",
            fg_color="#8B0000",
            hover_color="#A00000"
        )
        thread = threading.Thread(target=self._listen_thread, daemon=True)
        thread.start()

    def _listen_thread(self):
        def update_ui(msg):
            self.after(0, lambda: self.log(msg))

        self.voice_engine.listen_and_execute(update_ui)
        self.after(0, lambda: self.button_listen.configure(
            text="🎤 Écouter une commande",
            fg_color="#2E8B57",
            hover_color="#3EA067"
        ))
        self.is_listening = False

    # ============================================================
    #  AIDE (utilise get_resource_path pour fonctionner en exe)
    # ============================================================

    def open_help_buttons(self):
        help_file = get_resource_path("Aide_Controle_Boutons.txt")
        self._open_help_file(help_file, "Aide du mode Boutons")

    def open_help_voice(self):
        help_file = get_resource_path("Aide_Controle_Vocal_Audacity.txt")
        self._open_help_file(help_file, "Aide du mode Vocal")

    def _open_help_file(self, help_file, label):
        if os.path.exists(help_file):
            try:
                os.startfile(help_file)
                self.log(f"📖 {label} ouvert : {os.path.basename(help_file)}")
            except Exception as e:
                self.log(f"❌ Erreur lors de l'ouverture de l'aide : {e}")
        else:
            self.log(f"⚠️ Fichier d'aide introuvable : {os.path.basename(help_file)}")

    def on_closing(self):
        if self.controller:
            self.controller.close()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()