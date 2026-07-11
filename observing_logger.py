import sqlite3
from datetime import datetime, timezone
from tkinter import (
    Tk, Toplevel, Frame, Label, Entry, Text,
    Button, StringVar, END, messagebox, filedialog
)
from tkinter import ttk

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image as RLImage,
)
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch


# plotting gong stuff: 
from astropy.time import Time
import numpy
import matplotlib.pyplot as plt
from sunpy.net import Fido, attrs as a
import astropy.units as u
from sunpy import map as map
import os
import numpy as np
from matplotlib.widgets import Button as MplButton
from matplotlib.patches import Rectangle

class Config:
    def __init__(self, DB_NAME="observing_logs.db",
                  db_save_path=None, 
                  pdf_save_path=None,
                  verbose = False,
                  use_gong = True,
                  default_observer = None):
        
        self.DB_NAME = DB_NAME
        self.db_save_path = db_save_path
        self.pdf_save_path = pdf_save_path
        self.verbose = verbose
        self.use_gong = use_gong
        self.default_observer = default_observer


class DatabaseManager:
    """Handles all SQLite operations."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.db_name = cfg.DB_NAME
        self.initialize_database()

    def initialize_database(self):
        conn = sqlite3.connect(self.db_name)
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                local_time TEXT NOT NULL,
                utc_time TEXT NOT NULL,
                observer TEXT,
                telescope TEXT,
                instrument TEXT,
                target TEXT NOT NULL,
                seeing TEXT,
                notes TEXT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS log_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_id INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (log_id) REFERENCES logs(id)
            )
            """
        )

        conn.commit()
        conn.close()

    def set_database(self, db_name):
        self.db_name = db_name
        self.initialize_database()

    def add_log(
        self,
        observer,
        telescope,
        instrument,
        target,
        seeing,
        notes,
        local_time,
        utc_time,
    ):
        conn = sqlite3.connect(self.db_name)
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO logs (
                local_time,
                utc_time,
                observer,
                telescope,
                instrument,
                target,
                seeing,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                local_time,
                utc_time,
                observer,
                telescope,
                instrument,
                target,
                seeing,
                notes,
            ),
        )

        conn.commit()
        conn.close()

    def append_note_to_last_log(self, new_note):
        conn = sqlite3.connect(self.db_name)
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, notes
            FROM logs
            ORDER BY id DESC
            LIMIT 1
            """
        )

        row = cur.fetchone()

        if not row:
            conn.close()
            return False

        log_id, existing_notes = row

        if existing_notes and existing_notes.strip():
            # Keep exactly one line break between old and new note blocks.
            combined_notes = (
                f"{existing_notes.rstrip()}\n{new_note.strip()}"
            )
        else:
            combined_notes = new_note.strip()

        cur.execute(
            """
            UPDATE logs
            SET notes = ?
            WHERE id = ?
            """,
            (combined_notes, log_id),
        )

        conn.commit()
        conn.close()
        return True

    def add_image_to_last_log(self, image_path):
        conn = sqlite3.connect(self.db_name)
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id
            FROM logs
            ORDER BY id DESC
            LIMIT 1
            """
        )

        row = cur.fetchone()

        if not row:
            conn.close()
            return False

        log_id = row[0]
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur.execute(
            """
            INSERT INTO log_images (log_id, image_path, created_at)
            VALUES (?, ?, ?)
            """,
            (log_id, image_path, created_at),
        )

        conn.commit()
        conn.close()
        return True

    def get_images_for_log(self, log_id):
        conn = sqlite3.connect(self.db_name)
        cur = conn.cursor()

        cur.execute(
            """
            SELECT image_path
            FROM log_images
            WHERE log_id = ?
            ORDER BY id ASC
            """,
            (log_id,),
        )

        rows = cur.fetchall()
        conn.close()
        return [row[0] for row in rows]

    def get_all_logs(self):
        conn = sqlite3.connect(self.db_name)
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                id,
                local_time,
                utc_time,
                observer,
                telescope,
                instrument,
                target,
                seeing,
                notes
            FROM logs
            ORDER BY local_time ASC
            """
        )

        rows = cur.fetchall()

        conn.close()
        return rows
    
class gong_data_plotter:
    """
    load and plot the GONG files closest to the specified time, delete the GONG file locally afterwards.
    """

    def __init__(self, cfg):
        self.cfg = cfg

    def load_gong(self):
        """
        Downloads all HMI data within one minute of the passed time interval

        Parameters:
        -----------
        start_time (Time): The start time of the interval
        end_time (Time): The end time of the interval

        ** Currently only reads in middle file, not all related files **
        """
        time = Time.now()
        search_results = Fido.search(
            a.Instrument.bigbear,
            a.Physobs("intensity"),
            a.Time(time - 10 * u.minute, time + 1 * u.minute),
        )

        if len(search_results[0]) == 0:
            search_results = Fido.search(
            a.Instrument.learmonth,
            a.Physobs("intensity"),
            a.Time(time - 10 * u.minute, time + 1 * u.minute),
        )

        if len(search_results[0]) == 0:
            raise FileNotFoundError("No GONG files found for the specified time interval.")

        path_to_sunpy = "~/sunpy/data/observing_logger/"


        print(50 * '-')
        print(f'Loading GONG file: {str(search_results[0][-1][0])}')

        gong_file = Fido.fetch(
            search_results[0][-1], path=path_to_sunpy, progress=True, site="NSO"
        )

        print(50 * '-')

        if gong_file == []:
            raise FileNotFoundError("Can not open GONG file.")

        # read in the middle file using sunpy.map to extract the coordinates and data.
        gong = map.Map(gong_file[0])
        gong_data = np.divide(gong.data, np.nanmean(gong.data))
        image_time = gong.date

        return gong_data, image_time, gong_file
    
    def plot_gong(self, gong_data, image_time):
        """
        Plots the GONG data using matplotlib.

        Parameters:
        -----------
        gong_data (ndarray): 2D array of GONG intensity data
        image_time (Time): The time of the GONG image
        """
        save_time = Time(image_time).strftime("%Y%m%d_%H%M%S")
        image_path = os.path.abspath(f"gong_image_{save_time}.png")

        fig, ax = plt.subplots(figsize=(8, 8))
        plt.subplots_adjust(bottom=0.12)

        im = ax.imshow(
            gong_data,
            vmin=0.8,
            vmax=2,
            cmap="gray",
            origin="lower",
            extent=[-1000, 1000, -1000, 1000],
        )
        ax.set_title(f"GONG Image at {image_time}")
        ax.set_xlabel("X [arcsec]")
        ax.set_ylabel("Y [arcsec]")

        boxes = []
        first_corner = {"x": None, "y": None}
        saved = {"done": False}

        def save_clean_figure():
            # Hide helper controls/instructions so the exported image contains only plot content.
            clear_ax.set_visible(False)
            save_ax.set_visible(False)
            help_text.set_visible(False)
            fig.savefig(image_path, dpi=150, bbox_inches="tight")

        def clear_boxes(_event):
            first_corner["x"] = None
            first_corner["y"] = None

            for patch in list(boxes):
                patch.remove()

            boxes.clear()
            fig.canvas.draw_idle()

        def save_and_close(_event):
            save_clean_figure()
            saved["done"] = True
            plt.close(fig)

        def on_click(event):
            if event.inaxes != ax or event.xdata is None or event.ydata is None:
                return

            # Left click: place two corners to create a red box.
            if event.button == 1:
                if first_corner["x"] is None:
                    first_corner["x"] = event.xdata
                    first_corner["y"] = event.ydata
                    return

                x0 = first_corner["x"]
                y0 = first_corner["y"]
                x1 = event.xdata
                y1 = event.ydata

                rect = Rectangle(
                    (min(x0, x1), min(y0, y1)),
                    abs(x1 - x0),
                    abs(y1 - y0),
                    fill=False,
                    edgecolor="red",
                    linewidth=2,
                )
                ax.add_patch(rect)
                boxes.append(rect)

                first_corner["x"] = None
                first_corner["y"] = None
                fig.canvas.draw_idle()

            # Right click inside a box: remove the top-most matching box.
            elif event.button == 3:
                for rect in reversed(boxes):
                    bbox = rect.get_bbox()
                    if (
                        bbox.xmin <= event.xdata <= bbox.xmax
                        and bbox.ymin <= event.ydata <= bbox.ymax
                    ):
                        rect.remove()
                        boxes.remove(rect)
                        fig.canvas.draw_idle()
                        break

        def on_close(_event):
            if not saved["done"]:
                save_clean_figure()

        clear_ax = fig.add_axes([0.62, 0.02, 0.15, 0.05])
        clear_button = MplButton(clear_ax, "Clear Boxes")
        clear_button.on_clicked(clear_boxes)

        save_ax = fig.add_axes([0.79, 0.02, 0.17, 0.05])
        save_button = MplButton(save_ax, "Save & Close")
        save_button.on_clicked(save_and_close)

        fig.canvas.mpl_connect("button_press_event", on_click)
        fig.canvas.mpl_connect("close_event", on_close)

        help_text = fig.text(
            0.02,
            0.02,
            "Left click twice to add box | Right click inside box to remove",
            fontsize=9,
        )

        plt.show()

        if not os.path.exists(image_path):
            save_clean_figure()

        return image_path


    def delete_gong_file(self, gong_file):
        """
        Deletes the specified GONG FITS files from the local storage.

        Parameters:
        -----------
        gong_file (list): List of paths to the GONG FITS files to be deleted
        """
        for file in gong_file:
            if os.path.exists(file):
                os.remove(file)
            else:
                # this will trigger every time I save a new plot, so don't need an error message here. 
                pass

    
    def plot_and_delete_gong(self, gong_data, image_time, gong_file):
        """
        Loads and plots the GONG data for the time around the instance's time attribute.

        This method automatically sets the time interval to ten minutes before and one minute after the current time.
        """
        image_path = self.plot_gong(gong_data, image_time)
        self.delete_gong_file(gong_file)
        return image_path


    


class ObservingLogApp:
    """Main application."""

    def __init__(self, cfg, root):
        self.root = root
        self.cfg = cfg
        self.root.title("Observing Log")

        self.db = DatabaseManager(cfg)

        self.seeing_var = StringVar(value="Good")
        self.session_db_var = StringVar(value="")

        if cfg.use_gong:
            self.gong_plotter = gong_data_plotter(cfg)
            self.gong_data, self.gong_image_time, self.gong_file = self.gong_plotter.load_gong()

        self.create_widgets()
        self.update_session_db_label()

    def create_widgets(self):
        main = Frame(self.root, padx=10, pady=10)
        main.pack(fill="both", expand=True)

        # Session Metadata
        Label(main, text="Observer").grid(row=0, column=0, sticky="w")
        self.observer_entry = Entry(main, width=40)
        self.observer_entry.grid(row=0, column=1, pady=2)

        if self.cfg.default_observer:
            self.observer_entry.insert(0, self.cfg.default_observer)

        Label(main, text="Telescope").grid(row=1, column=0, sticky="w")
        self.telescope_entry = Entry(main, width=40)
        self.telescope_entry.grid(row=1, column=1, pady=2)

        Label(main, text="Instrument").grid(row=2, column=0, sticky="w")
        self.instrument_entry = Entry(main, width=40)
        self.instrument_entry.grid(row=2, column=1, pady=2)

        # Observation Info
        Label(main, text="Target").grid(row=3, column=0, sticky="w")
        self.target_entry = Entry(main, width=40)
        self.target_entry.grid(row=3, column=1, pady=2)

        Label(main, text="Seeing").grid(row=4, column=0, sticky="w")

        seeing_dropdown = ttk.Combobox(
            main,
            textvariable=self.seeing_var,
            values=[
                "Excellent",
                "Good",
                "Average",
                "Poor",
                "Very Poor",
            ],
            state="readonly",
            width=37,
        )
        seeing_dropdown.grid(row=4, column=1, pady=2)

        Label(main, text="Notes").grid(row=5, column=0, sticky="nw")

        self.notes_text = Text(main, width=50, height=10)
        self.notes_text.grid(row=5, column=1, pady=5)

        # Buttons
        btn_frame = Frame(main)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=10)

        Button(
            btn_frame,
            text="Save Log",
            width=15,
            command=self.save_log
        ).pack(side="left", padx=5)

        Button(
            btn_frame,
            text="Add Note",
            width=15,
            command=self.add_note_to_last_log
        ).pack(side="left", padx=5)

        Button(
            btn_frame,
            text="View Logs",
            width=15,
            command=self.view_logs
        ).pack(side="left", padx=5)

        Button(
            btn_frame,
            text="Export Session PDF",
            width=18,
            command=self.export_pdf
        ).pack(side="left", padx=5)

        Button(
            btn_frame,
            text="Add GONG Image",
            width=15,
            command=self.add_gong_image
        ).pack(side="left", padx=5)

        Button(
            btn_frame,
            text="New Session",
            width=15,
            command=self.start_new_session
        ).pack(side="left", padx=5)

        Label(
            main,
            textvariable=self.session_db_var,
            anchor="w"
        ).grid(row=7, column=0, columnspan=2, sticky="w")

    def update_session_db_label(self):
        db_display = os.path.abspath(self.db.db_name)
        self.session_db_var.set(f"Session DB: {db_display}")

    def start_new_session(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        initial_name = f"observing_logs_{timestamp}.db"

        new_db = filedialog.asksaveasfilename(
            title="Create New Session Database",
            initialfile=initial_name,
            defaultextension=".db",
            filetypes=[("SQLite Database", "*.db"), ("All Files", "*.*")],
        )

        if not new_db:
            return

        try:
            self.db.set_database(new_db)
            self.cfg.DB_NAME = new_db
            self.update_session_db_label()

            self.target_entry.delete(0, END)
            self.notes_text.delete("1.0", END)
            self.seeing_var.set("Good")

            messagebox.showinfo(
                "New Session",
                f"Now saving logs to:\n{new_db}"
            )
        except Exception as e:
            messagebox.showerror("Session Error", str(e))


    def save_log(self):
        target = self.target_entry.get().strip()

        if not target:
            messagebox.showerror(
                "Validation Error",
                "Target field cannot be empty."
            )
            return

        observer = self.observer_entry.get().strip()
        telescope = self.telescope_entry.get().strip()
        instrument = self.instrument_entry.get().strip()

        seeing = self.seeing_var.get()

        notes = self.notes_text.get("1.0", END).strip()

        local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        utc_time = (
            datetime.now(timezone.utc)
            .strftime("%Y-%m-%d %H:%M:%S UTC")
        )

        try:
            self.db.add_log(
                observer,
                telescope,
                instrument,
                target,
                seeing,
                notes,
                local_time,
                utc_time,
            )

            self.target_entry.delete(0, END)
            self.notes_text.delete("1.0", END)
            self.seeing_var.set("Good")

            messagebox.showinfo(
                "Success",
                "Log saved successfully."
            )

        except Exception as e:
            messagebox.showerror(
                "Database Error",
                str(e)
            )

    def add_note_to_last_log(self):
        note = self.notes_text.get("1.0", END).strip()

        if not note:
            messagebox.showerror(
                "Validation Error",
                "Notes field cannot be empty when adding a note."
            )
            return

        try:
            updated = self.db.append_note_to_last_log(note)

            if not updated:
                messagebox.showwarning(
                    "No Logs",
                    "No existing logs found. Save a log first."
                )
                return

            self.notes_text.delete("1.0", END)

            messagebox.showinfo(
                "Success",
                "Note appended to the most recent log."
            )

        except Exception as e:
            messagebox.showerror(
                "Database Error",
                str(e)
            )

    def load_gong_image(self):
        # I want to load the GONG image only once (so it's faster to pull up and plot.)
        # TODO: later, I'll add a button to update to the latest GONG image.

        if not self.use_gong:
            return

        try:
            self.gong_plotter = gong_data_plotter(self.cfg)
            self.gong_data, self.gong_image_time, self.gong_file = self.gong_plotter.load_gong()
        except Exception as e:
            messagebox.showerror("GONG Image Error", str(e))
    
    def add_gong_image(self):
        # TODO: Add image-selection workflow (for example, file picker dialog).
        # TODO: Add persistence for image metadata/storage and attach to a log.
        # Placeholder for future HMI image handling logic
        try:
            image_path = self.gong_plotter.plot_and_delete_gong(self.gong_data, self.gong_image_time, self.gong_file)

            attached = self.db.add_image_to_last_log(image_path)

            if not attached:
                if os.path.exists(image_path):
                    os.remove(image_path)
                messagebox.showwarning(
                    "No Logs",
                    "No existing logs found. Save a log first, then add a GONG image."
                )
                return

            messagebox.showinfo(
                "GONG Image Saved",
                f"Saved:\n{image_path}\n\n"
                "Image attached to the most recent log and will be included in PDF export."
            )
        except Exception as e:
            messagebox.showerror("GONG Image Error", str(e))
        

    def view_logs(self):
        rows = self.db.get_all_logs()

        window = Toplevel(self.root)
        window.title("Saved Logs")
        window.geometry("1200x500")

        columns = (
            "Local Time",
            "Target",
            "Seeing",
            "Observer",
            "Telescope",
            "Instrument",
            "Notes",
        )

        tree = ttk.Treeview(
            window,
            columns=columns,
            show="headings"
        )

        for c in columns:
            tree.heading(c, text=c)
            tree.column(c, width=150)

        scrollbar = ttk.Scrollbar(
            window,
            orient="vertical",
            command=tree.yview
        )

        tree.configure(yscrollcommand=scrollbar.set)

        for row in rows:
            (
                _id,
                local_time,
                utc_time,
                observer,
                telescope,
                instrument,
                target,
                seeing,
                notes,
            ) = row

            tree.insert(
                "",
                END,
                values=(
                    local_time,
                    target,
                    seeing,
                    observer,
                    telescope,
                    instrument,
                    notes,
                ),
            )

        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def export_pdf(self):
        try:
            logs = self.db.get_all_logs()

            if not logs:
                messagebox.showwarning(
                    "No Logs",
                    "No logs available for export."
                )
                return

            timestamp = datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )

            pdf_name = (
                f"observing_log_{timestamp}.pdf"
            )

            doc = SimpleDocTemplate(pdf_name)

            styles = getSampleStyleSheet()

            content = []

            content.append(
                Paragraph("Observing Log", styles["Title"])
            )

            content.append(
                Paragraph(
                    f"Generated: "
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    styles["Normal"]
                )
            )

            content.append(Spacer(1, 12))

            for row in logs:
                (
                    _id,
                    local_time,
                    utc_time,
                    observer,
                    telescope,
                    instrument,
                    target,
                    seeing,
                    notes,
                ) = row

                content.append(
                    Paragraph(
                        f"<b>Local Time:</b> {local_time}",
                        styles["Normal"]
                    )
                )

                content.append(
                    Paragraph(
                        f"<b>UTC Time:</b> {utc_time}",
                        styles["Normal"]
                    )
                )

                content.append(
                    Paragraph(
                        f"<b>Observer:</b> {observer}",
                        styles["Normal"]
                    )
                )

                content.append(
                    Paragraph(
                        f"<b>Telescope:</b> {telescope}",
                        styles["Normal"]
                    )
                )

                content.append(
                    Paragraph(
                        f"<b>Instrument:</b> {instrument}",
                        styles["Normal"]
                    )
                )

                content.append(
                    Paragraph(
                        f"<b>Target:</b> {target}",
                        styles["Normal"]
                    )
                )

                content.append(
                    Paragraph(
                        f"<b>Seeing:</b> {seeing}",
                        styles["Normal"]
                    )
                )

                content.append(
                    Paragraph(
                        f"<b>Notes:</b><br/>{(notes or '').replace(chr(10), '<br/>')}",
                        styles["Normal"]
                    )
                )

                image_paths = self.db.get_images_for_log(_id)
                existing_images = [p for p in image_paths if os.path.exists(p)]

                if existing_images:
                    content.append(
                        Paragraph("<b>GONG Images:</b>", styles["Normal"])
                    )

                    for img_path in existing_images:
                        content.append(
                            RLImage(
                                img_path,
                                width=2.25 * inch,
                                height=2.25 * inch,
                            )
                        )
                        content.append(Spacer(1, 6))

                content.append(Spacer(1, 12))

            doc.build(content)

            messagebox.showinfo(
                "PDF Export Complete",
                f"Saved:\n{pdf_name}"
            )

        except Exception as e:
            messagebox.showerror(
                "PDF Export Error",
                str(e)
            )


def main():
    cfg = Config(default_observer="James Crowley")

    root = Tk()
    app = ObservingLogApp(cfg, root)
    root.mainloop()


if __name__ == "__main__":
    main()