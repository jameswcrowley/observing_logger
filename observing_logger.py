import sqlite3
from datetime import datetime, timezone
from tkinter import (
    Tk, Toplevel, Frame, Label, Entry, Text,
    Button, StringVar, END, messagebox
)
from tkinter import ttk

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet

from astropy.time import Time
import numpy
import matplotlib.pyplot as plt
from sunpy.net import Fido, attrs as a
import astropy.units as u
from sunpy import map as map

class Config:
    def __init__(self, DB_NAME="observing_logs.db",
                  db_save_path=None, 
                  pdf_save_path=None,
                  verbose = False,
                  use_HMI = True,
                  default_observer = None):
        
        self.DB_NAME = DB_NAME
        self.db_save_path = db_save_path
        self.pdf_save_path = pdf_save_path
        self.use_HMI = use_HMI
        self.verbose = verbose
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

        conn.commit()
        conn.close()

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
    
class HMI_data_plotter:
    """
    load and plot the HMI files closest to the specified time, delete the HMI file locally afterwards.
    """

    def __init__(self, cfg, time):
        self.cfg = cfg
        self.time = time

    def load_hmi(self, time: Time):
        """
        Downloads all HMI data within one minute of the passed time interval

        Parameters:
        -----------
        start_time (Time): The start time of the interval
        end_time (Time): The end time of the interval

        ** Currently only reads in middle file, not all related files **
        """
        search_results = Fido.search(
            a.Instrument.hmi,
            a.Physobs("intensity"),
            a.Time(time - 1 * u.minute, time + 1 * u.minute),
        )
        path_to_sunpy = "~/sunpy/data/observing_logger/"

        hmi_files = Fido.fetch(
            search_results, path=path_to_sunpy, progress=self.cfg.verbose, site="NSO"
        )

        if hmi_files == []:
            raise FileNotFoundError("No HMI files found for the specified time interval.")

        # read in the middle file using scipy.map to extract the coordinates and data.
        hmi = map.Map(hmi_files[0])

        # read in the x and y coordinates as seperate arrays.
        hmix = map.all_coordinates_from_map(hmi).Tx
        hmiy = map.all_coordinates_from_map(hmi).Ty
        
        # read in the intensity data as a 2D array.  
        hmi_data = hmi.data
        hmi_data /= np.max(hmi.data)

        image_time = hmi.date

        return hmix, hmiy, hmi_data, image_time
    
    def plot_hmi(self, hmix, hmiy, hmi_data, image_time):
        """
        Plots the HMI data using matplotlib.

        Parameters:
        -----------
        hmix (ndarray): X coordinates of the HMI data
        hmiy (ndarray): Y coordinates of the HMI data
        hmi_data (ndarray): 2D array of HMI intensity data
        image_time (Time): The time of the HMI image
        """
        plt.figure(figsize=(8, 8))
        plt.imshow(hmi_data, extent=[hmix.min(), hmix.max(), hmiy.min(), hmiy.max()], origin='lower', cmap='gray')
        plt.colorbar(label='Intensity')
        plt.title(f'HMI Image at {image_time}')
        plt.xlabel('X [arcsec]')
        plt.ylabel('Y [arcsec]')
        plt.show()


    def load_and_plot_HMI(self):
        """
        Loads and plots the HMI data for the time around the instance's time attribute.

        This method automatically sets the time interval to one minute before and after the instance's time.
        """
        hmix, hmiy, hmi_data, image_time = self.load_hmi(self.time)
        self.plot_hmi(hmix, hmiy, hmi_data, image_time)

    


class ObservingLogApp:
    """Main application."""

    def __init__(self, cfg, root):
        self.root = root
        self.cfg = cfg
        self.root.title("Observing Log")

        self.db = DatabaseManager(cfg)

        self.seeing_var = StringVar(value="Good")

        self.create_widgets()

    def create_widgets(self):
        main = Frame(self.root, padx=10, pady=10)
        main.pack(fill="both", expand=True)

        # Session Metadata
        Label(main, text="Observer").grid(row=0, column=0, sticky="w")
        self.observer_entry = Entry(main, width=40)
        self.observer_entry.grid(row=0, column=1, pady=2)

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
            text="Add HMI Image",
            width=15,
            command=self.add_hmi_image
        ).pack(side="left", padx=5)


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

    def add_hmi_image(self):
        # TODO: Add image-selection workflow (for example, file picker dialog).
        # TODO: Add persistence for image metadata/storage and attach to a log.
        if not self.cfg.use_HMI:
            messagebox.showwarning(
                "HMI Disabled",
                "HMI functionality is disabled in the current configuration."
            )
            #return
        else:
            # Placeholder for future HMI image handling logic
            local_time = Time(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            hmi_plotter = HMI_data_plotter(self.cfg, local_time)
            hmi_plotter.load_and_plot_HMI()
            

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
    cfg = Config(use_HMI = False,
                 default_observer="James Crowley")

    root = Tk()
    app = ObservingLogApp(cfg, root)
    root.mainloop()


if __name__ == "__main__":
    main()