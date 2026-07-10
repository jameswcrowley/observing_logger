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


class Config:
    def __init__(self, DB_NAME="observing_logs.db", db_save_path=None, pdf_save_path=None):
        self.DB_NAME = DB_NAME
        self.db_save_path = db_save_path
        self.pdf_save_path = pdf_save_path


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

        if existing_notes:
            # TODO: this is not actually adding new notes to a new line. 
            combined_notes = f"{existing_notes}\n{new_note}"
        else:
            combined_notes = new_note

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
        messagebox.showinfo(
            "Not Implemented",
            "'Add HMI Image' functionality will be added in a future update."
        )

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
                        f"<b>Notes:</b><br/>{notes}",
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
    cfg = Config()

    root = Tk()
    app = ObservingLogApp(cfg, root)
    root.mainloop()


if __name__ == "__main__":
    main()