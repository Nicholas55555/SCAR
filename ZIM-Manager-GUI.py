import logging
import os
import sys
import pathlib
import re
import shutil
import subprocess
import time

from libzim.reader import Archive
from libzim.writer import Creator, Item, StringProvider, FileProvider, Hint
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLineEdit, QFormLayout,
    QFileDialog, QMessageBox, QComboBox, QGridLayout, QTextEdit, QListWidget
)
from PySide6.QtCore import Qt

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.basicConfig(level=logging.WARNING)

class ZimManager:
    namespace_descriptions = {
        "A": "Article",
        "B": "Deleted articles",
        "C": "Category entries",
        "I": "Images",
        "M": "Metadata",
        "S": "Stylesheets",
        "F": "Other files",
        "V": "Videos",
        "X": "Special entries"
    }

    def __init__(self, zim_file_path=None):
        self.zim_file_path = zim_file_path
        self.zim = Archive(zim_file_path) if zim_file_path else None

    def get_namespace_description(self, namespace):
        return self.namespace_descriptions.get(namespace, f"Unknown ({namespace})")

    def get_namespaces(self):
        namespaces = self.view_all_namespaces()
        return {**self.namespace_descriptions, **namespaces, "ALL": "Select all namespaces", "UNKNOWN": "Select all unknown namespaces"}

    def set_namespace(self, selected_ns):
        namespaces = self.get_namespaces()
        selected_ns_upper = selected_ns.upper().strip()

        if selected_ns_upper == "ALL":
            self.selected_namespace = None
        elif selected_ns_upper == "UNKNOWN":
            self.selected_namespace = "UNKNOWN"
        elif selected_ns_upper in namespaces:
            self.selected_namespace = namespaces[selected_ns_upper]
        else:
            raise ValueError("Invalid namespace selected.")

        return self.selected_namespace

    def view_all_namespaces(self):
        namespaces = {}
        for i in range(self.zim.entry_count):
            entry = self.get_entry(i)
            namespace_char = entry.path[0] if entry.path else None
            if namespace_char not in self.namespace_descriptions and namespace_char:
                namespaces[namespace_char] = f"Unknown_{namespace_char}"
        return namespaces

    def get_entry(self, entry_id):
        return self.zim._get_entry_by_id(entry_id)

    def extract_all_text(self, output_file, namespace):
        with open(output_file, 'w', encoding='utf-8') as outfile:
            for i in range(self.zim.entry_count):
                entry = self.get_entry(i)
                if entry.path.startswith(namespace):
                    article = entry.get_item().content.tobytes().decode('utf-8', errors='ignore')
                    body = re.search(r"<body.*?>(.*?)</body>", article, re.S)
                    if body:
                        clean_text = re.sub('<[^<]+?>', '', body.group(1))
                        outfile.write(clean_text + "\n\n")

    def extract_titles(self, namespace):
        results = []
        for i in range(self.zim.entry_count):
            entry = self.get_entry(i)
            if entry.path.startswith(namespace):
                results.append((entry.path, entry.title))
        return results

    def list_all_paths(self, namespace=None):
        paths = []
        for i in range(self.zim.entry_count):
            entry = self.get_entry(i)
            if namespace is None or entry.path.startswith(namespace):
                paths.append(entry.path)
        return paths

    def save_titles_to_file(self, output_file_path, namespace):
        results = self.extract_titles(namespace)
        if not results:
            raise ValueError("No titles found.")

        with open(output_file_path, 'w', encoding='utf-8') as outfile:
            for url, title in results:
                outfile.write(f"Title: {title}\nURL: {url}\n\n")

    def save_selected_articles(self, output_file, selected_urls):
        with open(output_file, 'w', encoding='utf-8') as outfile:
            for selected_url in selected_urls:
                entry = self.zim.get_entry_by_path(selected_url)
                if entry:
                    article = entry.get_item().content.tobytes().decode('utf-8', errors='ignore')
                    body = re.search(r"<body.*?>(.*?)</body>", article, re.S)
                    if body:
                        clean_text = re.sub('<[^<]+?>', '', body.group(1))
                        outfile.write(f"Title: {entry.title}\n\n{clean_text}\n\n")
                    else:
                        clean_text = re.sub('<[^<]+?>', '', article)
                        outfile.write(f"Title: {entry.title}\n\n{clean_text}\n\n")

    def view_file(self, file_path):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            return file.read()

    def urlopener(self, url):
        if url:
            try:
                if sys.platform == 'win32':
                    subprocess.run(['start', url], check=True, shell=True)
                elif sys.platform == 'darwin':
                    subprocess.run(['open', url], check=True)
                else:
                    subprocess.run(['xdg-open', url], check=True)
                return f"Opening: {url}"
            except Exception as e:
                raise RuntimeError(f"Failed to open URL: {e}")
        else:
            raise ValueError("No URL entered")

    def extract_html_files(self, output_dir, namespace):
        self.extract_by_mimetype(output_dir, namespace, "text/html")

    def extract_images(self, output_dir, namespace):
        self.extract_by_mimetype(output_dir, namespace, "image/")

    def extract_css_files(self, output_dir, namespace):
        self.extract_by_mimetype(output_dir, namespace, "text/css")

    def extract_js_files(self, output_dir, namespace):
        self.extract_by_mimetype(output_dir, namespace, "application/javascript")

    def _sanitize_filename(self, filename):
        return re.sub(r'[<>:"/\\|?*]', '_', filename)

    def extract_by_mimetype(self, output_dir, namespace, mimetype):
        pathlib.Path(output_dir).mkdir(parents=True, exist_ok=True)

        for i in range(self.zim.entry_count):
            entry = self.get_entry(i)
            if not entry.path:
                print(f"Warning: Entry {i} has an empty path, skipping.")
                continue

            item = entry.get_item()
            item_mimetype = self._determine_mimetype(entry.path)
            entry_namespace = entry.path[0]

            if ((namespace is None or entry_namespace == namespace) or
                (namespace == "UNKNOWN" and self.get_namespace_description(entry_namespace).startswith("Unknown"))) \
                    and item_mimetype.startswith(mimetype):

                content = item.content.tobytes()
                file_extension = item_mimetype.split('/')[-1]
                sanitized_path = self._sanitize_filename(entry.path)
                file_path = pathlib.Path(output_dir) / f"{sanitized_path}.{file_extension}"
                file_path.parent.mkdir(parents=True, exist_ok=True)

                if any(media in mimetype for media in ['image', 'video', 'application/octet-stream']):
                    with open(file_path, 'wb') as file:
                        file.write(content)
                else:
                    with open(file_path, 'w', encoding='utf-8', errors='ignore') as file:
                        file.write(content.decode('utf-8', errors='ignore'))

                print(f"Extracted: {file_path}")

        print(f"All files of type {mimetype} extracted to {output_dir}")

    def _determine_mimetype(self, path):
        if path.startswith("A/"):
            return "text/html"
        elif path.endswith(".html") or path.endswith(".htm"):
            return "text/html"
        elif path.endswith(".png"):
            return "image/png"
        elif path.endswith(".jpg") or path.endswith(".jpeg"):
            return "image/jpeg"
        elif path.endswith(".css"):
            return "text/css"
        elif path.endswith(".js"):
            return "application/javascript"
        elif path.endswith(".pdf"):
            return "application/pdf"
        elif path.endswith(".zip"):
            return "application/zip"
        elif path.endswith(".mp4"):
            return "video/mp4"
        elif path.endswith(".webm"):
            return "video/webm"
        elif path.endswith(".ogg"):
            return "video/ogg"
        else:
            return "application/octet-stream"

    class MyItem(Item):
        def __init__(self, title, path, content="", fpath=None):
            super().__init__()
            self._path = path
            self._title = title
            self._content = content
            self._fpath = fpath

        def get_path(self):
            return self._path

        def get_title(self):
            return self._title

        def get_mimetype(self):
            if self._path.endswith(".html") or self._path.endswith(".htm"):
                return "text/html"
            elif self._path.endswith(".png"):
                return "image/png"
            elif self._path.endswith(".jpg") or self._path.endswith(".jpeg"):
                return "image/jpeg"
            elif self._path.endswith(".css"):
                return "text/css"
            elif self._path.endswith(".js"):
                return "application/javascript"
            else:
                return "application/octet-stream"

        def get_contentprovider(self):
            if self._fpath:
                return FileProvider(self._fpath)
            return StringProvider(self._content)

        def get_hints(self):
            return {Hint.FRONT_ARTICLE: True}

    def create_zim_file(self, output_file, articles, main_article_path):
        temp_output_file = f"{output_file}.tmp"
        backup_file = f"{output_file}.backup"
        try:
            with Creator(temp_output_file).config_indexing(True, "eng") as creator:
                creator.set_mainpath(main_article_path)
                for article in articles:
                    print(f"Processing article: {article['title']} with path: {article['path']}")
                    item = self.MyItem(article['title'], article['path'], article['content'])
                    creator.add_item(item)

                for name, value in {
                    "creator": "python-libzim",
                    "description": "Created in python",
                    "name": "my-zim",
                    "publisher": "You",
                    "title": "Test ZIM",
                    "language": "eng",
                    "date": "2024-06-30"
                }.items():
                    creator.add_metadata(name.title(), value)

            if os.path.exists(output_file):
                try:
                    os.rename(output_file, backup_file)
                except PermissionError:
                    print("Permission denied while renaming the existing file, retrying...")
                    time.sleep(2)
                    os.rename(output_file, backup_file)

            shutil.move(temp_output_file, output_file)
            print(f"ZIM file created successfully at {output_file}")

            if os.path.exists(backup_file):
                os.remove(backup_file)

        finally:
            if os.path.exists(temp_output_file):
                os.remove(temp_output_file)

    def create_zim_file_from_directory_auto(self, output_file, main_article_path, input_directory):
        articles = []

        for root, _, files in os.walk(input_directory):
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, input_directory)

                if file.endswith(".html") or file.endswith(".htm"):
                    namespace = "A"
                elif file.endswith(".png") or file.endswith(".jpg") or file.endswith(".jpeg"):
                    namespace = "I"
                elif file.endswith(".css"):
                    namespace = "S"
                elif file.endswith(".js"):
                    namespace = "S"
                elif file.endswith(".pdf"):
                    namespace = "F"
                elif file.endswith(".mp4") or file.endswith(".webm") or file.endswith(".ogg"):
                    namespace = "V"
                else:
                    namespace = "F"

                zim_path = f"{namespace}/{relative_path.replace(os.path.sep, '/')}"

                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                articles.append({
                    "title": os.path.splitext(file)[0],
                    "path": zim_path,
                    "content": content
                })

        self.create_zim_file(output_file, articles, main_article_path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("ZimManager")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        grid_layout = QGridLayout(central_widget)

        zimmanager_top_right_widget = QWidget()
        zimmanager_top_right_layout = QVBoxLayout(zimmanager_top_right_widget)
        zimmanager_top_right_layout.setContentsMargins(0, 0, 0, 0)
        zimmanager_top_right_layout.setSpacing(10)
        self.add_zimmanager_functions(zimmanager_top_right_layout)
        grid_layout.addWidget(zimmanager_top_right_widget, 0, 1)

        zimmanager_bottom_right_widget = QWidget()
        zimmanager_bottom_right_layout = QVBoxLayout(zimmanager_bottom_right_widget)
        zimmanager_bottom_right_layout.setContentsMargins(0, 0, 0, 0)
        zimmanager_bottom_right_layout.setSpacing(10)
        self.add_zim_creation_functionality(zimmanager_bottom_right_layout)
        grid_layout.addWidget(zimmanager_bottom_right_widget, 1, 1)

        self.showMaximized()

    def add_zimmanager_functions(self, layout):
        zimmanager_form_layout = QFormLayout()

        self.zim_file_input = QLineEdit()
        select_zim_btn = QPushButton("Select ZIM File")
        select_zim_btn.clicked.connect(lambda: self.select_file(self.zim_file_input))
        zimmanager_form_layout.addRow(select_zim_btn, self.zim_file_input)

        self.mimetype_combo = QComboBox()
        self.mimetype_combo.addItems([
            "text/html",
            "image/png",
            "image/jpeg",
            "text/css",
            "application/javascript",
            "application/pdf",
            "text/plain",
            "application/zip",
            "video/mp4",
            "video/webm",
            "video/ogg"
        ])
        zimmanager_form_layout.addRow("MIME Type", self.mimetype_combo)

        self.zim_output_dir_input = QLineEdit()
        select_zim_output_dir_btn = QPushButton("Select Output Directory")
        select_zim_output_dir_btn.clicked.connect(lambda: self.select_directory(self.zim_output_dir_input))
        zimmanager_form_layout.addRow(select_zim_output_dir_btn, self.zim_output_dir_input)

        run_extract_mimetype_btn = QPushButton("Extract by MIME Type")
        run_extract_mimetype_btn.clicked.connect(self.run_extract_mimetype)
        zimmanager_form_layout.addWidget(run_extract_mimetype_btn)

        self.titles_output_file_input = QLineEdit()
        select_titles_output_file_btn = QPushButton("Select Output File for Titles")
        select_titles_output_file_btn.clicked.connect(lambda: self.select_save_file(self.titles_output_file_input))
        zimmanager_form_layout.addRow(select_titles_output_file_btn, self.titles_output_file_input)

        run_extract_titles_btn = QPushButton("Extract Titles")
        run_extract_titles_btn.clicked.connect(self.run_extract_titles)
        zimmanager_form_layout.addWidget(run_extract_titles_btn)

        self.list_paths_widget = QListWidget()
        run_list_paths_btn = QPushButton("List All Paths")
        run_list_paths_btn.clicked.connect(self.run_list_paths)
        zimmanager_form_layout.addWidget(run_list_paths_btn)
        zimmanager_form_layout.addWidget(self.list_paths_widget)

        self.selected_articles_input = QTextEdit()
        self.selected_articles_output_file_input = QLineEdit()
        select_selected_articles_output_file_btn = QPushButton("Select Output File for Selected Articles")
        select_selected_articles_output_file_btn.clicked.connect(lambda: self.select_save_file(self.selected_articles_output_file_input))
        zimmanager_form_layout.addRow(select_selected_articles_output_file_btn, self.selected_articles_output_file_input)

        run_save_selected_articles_btn = QPushButton("Save Selected Articles")
        run_save_selected_articles_btn.clicked.connect(self.run_save_selected_articles)
        zimmanager_form_layout.addRow("Enter URLs of Articles to Save (one per line):", self.selected_articles_input)
        zimmanager_form_layout.addWidget(run_save_selected_articles_btn)

        layout.addLayout(zimmanager_form_layout)

    def add_zim_creation_functionality(self, layout):
        create_zim_form_layout = QFormLayout()

        self.zim_output_file_input = QLineEdit()
        select_zim_output_btn = QPushButton("Select ZIM Output File")
        select_zim_output_btn.clicked.connect(lambda: self.select_save_file(self.zim_output_file_input))
        create_zim_form_layout.addRow(select_zim_output_btn, self.zim_output_file_input)

        self.main_article_path_input = QLineEdit()
        main_article_path_input = QPushButton("Main Article Path")
        main_article_path_input.clicked.connect(lambda: self.select_file(self.input_dir_input))
        create_zim_form_layout.addRow(main_article_path_input, self.main_article_path_input)
        self.input_dir_input = QLineEdit()
        select_input_dir_btn = QPushButton("Select Input Directory")
        select_input_dir_btn.clicked.connect(lambda: self.select_directory(self.input_dir_input))
        create_zim_form_layout.addRow(select_input_dir_btn, self.input_dir_input)

        run_create_zim_btn = QPushButton("Create ZIM File")
        run_create_zim_btn.clicked.connect(self.run_create_zim_file)
        create_zim_form_layout.addWidget(run_create_zim_btn)

        layout.addLayout(create_zim_form_layout)

    def run_extract_mimetype(self):
        zim_file = self.zim_file_input.text()
        output_dir = self.zim_output_dir_input.text()
        mimetype = self.mimetype_combo.currentText()

        if not zim_file or not output_dir:
            QMessageBox.warning(self, "Input Error", "Please select a ZIM file and specify an output directory.")
            return

        manager = ZimManager(zim_file)
        manager.extract_by_mimetype(output_dir, None, mimetype)
        QMessageBox.information(self, "Extract by MIME Type", f"Files of MIME type {mimetype} extracted to {output_dir}")

    def run_extract_titles(self):
        zim_file = self.zim_file_input.text()
        output_file = self.titles_output_file_input.text()
        if not zim_file or not output_file:
            QMessageBox.warning(self, "Input Error", "Please select a ZIM file and specify an output file.")
            return

        manager = ZimManager(zim_file)
        selected_namespace = None

        manager.save_titles_to_file(output_file, selected_namespace)
        QMessageBox.information(self, "Extract Titles", f"Titles extracted to {output_file}")

    def run_list_paths(self):
        zim_file = self.zim_file_input.text()
        if not zim_file:
            QMessageBox.warning(self, "Input Error", "Please select a ZIM file first.")
            return

        manager = ZimManager(zim_file)
        namespace = None
        paths = manager.list_all_paths(namespace)
        self.list_paths_widget.clear()
        self.list_paths_widget.addItems(paths)

    def run_save_selected_articles(self):
        zim_file = self.zim_file_input.text()
        output_file = self.selected_articles_output_file_input.text()
        selected_urls = self.selected_articles_input.toPlainText().splitlines()

        if not zim_file or not output_file or not selected_urls:
            QMessageBox.warning(self, "Input Error", "Please select a ZIM file, specify an output file, and enter the URLs.")
            return

        manager = ZimManager(zim_file)
        manager.save_selected_articles(output_file, selected_urls)
        QMessageBox.information(self, "Save Selected Articles", f"Articles saved to {output_file}")

    def run_create_zim_file(self):
        zim_output_file = self.zim_output_file_input.text()
        main_article_path = self.main_article_path_input.text()
        input_directory = self.input_dir_input.text()

        if not zim_output_file or not main_article_path or not input_directory:
            QMessageBox.warning(self, "Input Error", "Please fill in all fields before creating the ZIM file.")
            return

        manager = ZimManager()
        manager.create_zim_file_from_directory_auto(zim_output_file, main_article_path, input_directory)
        QMessageBox.information(self, "ZIM File Creation", f"ZIM file created successfully at {zim_output_file}")

    def select_file(self, line_edit):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "All Files (*)")
        if file_path:
            line_edit.setText(file_path)

    def select_save_file(self, line_edit):
        file_path, _ = QFileDialog.getSaveFileName(self, "Select Save File", "", "All Files (*)")
        if file_path:
            line_edit.setText(file_path)

    def select_directory(self, line_edit):
        directory_path = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory_path:
            line_edit.setText(directory_path)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    main_window = MainWindow()
    main_window.show()

    sys.exit(app.exec())
