"""
Combined Payroll and Timesheet Data Extractor GUI Application
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from tkcalendar import DateEntry
import pandas as pd
from pdf_parser import PayrollPDFParser
from timesheet_extractor import TimesheetExtractor
import os


class PayrollPDFTab:
    """Tab for PDF payroll extraction"""

    def __init__(self, parent):
        self.parent = parent
        self.pdf_path = None
        self.extracted_data = []
        self.parser = PayrollPDFParser()

        self.create_widgets()

    def create_widgets(self):
        """Create widgets for PDF extraction tab"""
        # Configure grid
        self.parent.columnconfigure(0, weight=1)
        self.parent.rowconfigure(2, weight=1)

        # File Selection
        file_frame = ttk.LabelFrame(self.parent, text="1. Select PDF File", padding="10")
        file_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=10, pady=(10, 5))
        file_frame.columnconfigure(1, weight=1)

        self.file_label = ttk.Label(file_frame, text="No file selected", foreground="gray")
        self.file_label.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))

        select_btn = ttk.Button(file_frame, text="Browse PDF File...", command=self.select_file)
        select_btn.grid(row=1, column=0, sticky=tk.W)

        extract_btn = ttk.Button(file_frame, text="Extract Data", command=self.extract_data)
        extract_btn.grid(row=1, column=1, sticky=tk.E, padx=(10, 0))

        # Date Selection
        date_frame = ttk.LabelFrame(self.parent, text="2. Set Pay Period Ending Date", padding="10")
        date_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=10, pady=5)

        ttk.Label(date_frame, text="Ending Date:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))

        self.date_picker = DateEntry(
            date_frame,
            width=12,
            background='darkblue',
            foreground='white',
            borderwidth=2,
            date_pattern='mm/dd/yyyy'
        )
        self.date_picker.grid(row=0, column=1, sticky=tk.W)

        # Preview
        preview_frame = ttk.LabelFrame(self.parent, text="3. Preview Extracted Data", padding="10")
        preview_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=10, pady=5)
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        tree_scroll = ttk.Scrollbar(preview_frame)
        tree_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))

        self.tree = ttk.Treeview(
            preview_frame,
            columns=("Employee ID", "Employee Name", "REG Hours", "OT Hours", "DBL Hours"),
            show="headings",
            yscrollcommand=tree_scroll.set
        )
        tree_scroll.config(command=self.tree.yview)

        self.tree.heading("Employee ID", text="Employee ID")
        self.tree.heading("Employee Name", text="Employee Name")
        self.tree.heading("REG Hours", text="REG Hours")
        self.tree.heading("OT Hours", text="OT Hours")
        self.tree.heading("DBL Hours", text="DBL Hours")

        self.tree.column("Employee ID", width=100)
        self.tree.column("Employee Name", width=200)
        self.tree.column("REG Hours", width=100)
        self.tree.column("OT Hours", width=100)
        self.tree.column("DBL Hours", width=100)

        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Export
        export_frame = ttk.Frame(self.parent)
        export_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), padx=10, pady=5)
        export_frame.columnconfigure(0, weight=1)

        export_btn = ttk.Button(export_frame, text="4. Export to CSV", command=self.export_to_csv)
        export_btn.grid(row=0, column=0, sticky=tk.E)

        # Status
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.parent, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=4, column=0, sticky=(tk.W, tk.E), padx=10, pady=(5, 10))

    def select_file(self):
        filename = filedialog.askopenfilename(
            title="Select Payroll PDF Report",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if filename:
            self.pdf_path = filename
            display_name = os.path.basename(filename)
            self.file_label.config(text=f"Selected: {display_name}", foreground="black")
            self.status_var.set(f"File selected: {display_name}")

    def extract_data(self):
        if not self.pdf_path:
            messagebox.showwarning("No File", "Please select a PDF file first.")
            return

        try:
            self.status_var.set("Extracting data from PDF...")
            self.parent.update()

            for item in self.tree.get_children():
                self.tree.delete(item)

            self.extracted_data = self.parser.parse_payroll_pdf(self.pdf_path)

            if not self.extracted_data:
                messagebox.showwarning("No Data", "No payroll data found in the PDF.")
                self.status_var.set("No data extracted")
                return

            for employee in self.extracted_data:
                self.tree.insert("", tk.END, values=(
                    employee['employee_id'],
                    employee['employee_name'],
                    f"{employee['reg_hours']:.2f}",
                    f"{employee['ot_hours']:.2f}",
                    f"{employee['dbl_hours']:.2f}"
                ))

            self.status_var.set(f"Extracted data for {len(self.extracted_data)} employees")
            messagebox.showinfo("Success", f"Extracted payroll data for {len(self.extracted_data)} employees.")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to extract data:\n{str(e)}")
            self.status_var.set("Error during extraction")

    def export_to_csv(self):
        if not self.extracted_data:
            messagebox.showwarning("No Data", "Please extract data from a PDF first.")
            return

        try:
            ending_date_formatted = self.date_picker.get_date().strftime('%m/%d/%Y')
            ending_date_filename = self.date_picker.get_date().strftime('%Y%m%d')

            csv_data = []
            for employee in self.extracted_data:
                csv_data.append({
                    'Ending': ending_date_formatted,
                    'Employee': employee['employee_id'],
                    'Label': employee['employee_name'],
                    'Hours_1': employee['reg_hours'],
                    'Hours_2': employee['ot_hours'],
                    'Hours_3': employee['dbl_hours'],
                    'Hours_T': 0
                })

            df = pd.DataFrame(csv_data)
            default_filename = f"payroll_export_{ending_date_filename}.csv"

            save_path = filedialog.asksaveasfilename(
                title="Save CSV File",
                defaultextension=".csv",
                initialfile=default_filename,
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
            )

            if save_path:
                df.to_csv(save_path, index=False)
                self.status_var.set(f"Exported to: {os.path.basename(save_path)}")
                messagebox.showinfo("Success", f"Payroll data successfully exported to:\n{save_path}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to export data:\n{str(e)}")
            self.status_var.set("Error during export")


class TimesheetTab:
    """Tab for Excel timesheet extraction"""

    def __init__(self, parent):
        self.parent = parent
        self.timesheet_paths = []
        self.extracted_data = []
        self.extractor = TimesheetExtractor()

        # Define name order for sorting
        self.name_order = [
            "Daniel Trif",
            "Jerry Jeremias",
            #"Paul Robertson",
            "Zachary Ebbinghaus",
            "Florin Moldovan",
            "Jarrett Zorzi",
            "Yousof Saleh",
            "Henry Andkilde",
            "Matina Rahbar"
        ]

        self.create_widgets()

    def create_widgets(self):
        """Create widgets for timesheet extraction tab"""
        self.parent.columnconfigure(0, weight=1)
        self.parent.rowconfigure(1, weight=1)

        # File Selection
        file_frame = ttk.LabelFrame(self.parent, text="1. Select Timesheet Files (.xlsx)", padding="10")
        file_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=10, pady=(10, 5))
        file_frame.columnconfigure(0, weight=1)

        self.file_listbox = tk.Listbox(file_frame, height=4)
        self.file_listbox.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 5))

        btn_frame = ttk.Frame(file_frame)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E))

        select_btn = ttk.Button(btn_frame, text="Browse Files...", command=self.select_files)
        select_btn.grid(row=0, column=0, sticky=tk.W)

        clear_btn = ttk.Button(btn_frame, text="Clear", command=self.clear_files)
        clear_btn.grid(row=0, column=1, sticky=tk.W, padx=(5, 0))

        extract_btn = ttk.Button(btn_frame, text="Extract Data", command=self.extract_data)
        extract_btn.grid(row=0, column=2, sticky=tk.E, padx=(10, 0))

        btn_frame.columnconfigure(2, weight=1)

        # Preview
        preview_frame = ttk.LabelFrame(self.parent, text="2. Preview Extracted Data", padding="10")
        preview_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=10, pady=5)
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)

        tree_scroll = ttk.Scrollbar(preview_frame)
        tree_scroll.grid(row=0, column=1, sticky=(tk.N, tk.S))

        columns = ("Name", "End Date", "Reg", "OT1", "OT2", "Drive", "Sick", "Vac", "Hol", "NB")
        self.tree = ttk.Treeview(
            preview_frame,
            columns=columns,
            show="headings",
            yscrollcommand=tree_scroll.set
        )
        tree_scroll.config(command=self.tree.yview)

        self.tree.heading("Name", text="Employee Name")
        self.tree.heading("End Date", text="End Date")
        self.tree.heading("Reg", text="Regular")
        self.tree.heading("OT1", text="OT1")
        self.tree.heading("OT2", text="OT2")
        self.tree.heading("Drive", text="Drive")
        self.tree.heading("Sick", text="Sick")
        self.tree.heading("Vac", text="Vacation")
        self.tree.heading("Hol", text="Holiday")
        self.tree.heading("NB", text="Non-Bill")

        self.tree.column("Name", width=150)
        for col in ["End Date", "Reg", "OT1", "OT2", "Drive", "Sick", "Vac", "Hol", "NB"]:
            self.tree.column(col, width=80)

        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Export
        export_frame = ttk.Frame(self.parent)
        export_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), padx=10, pady=5)
        export_frame.columnconfigure(0, weight=1)

        export_btn = ttk.Button(export_frame, text="3. Export to CSV", command=self.export_to_csv)
        export_btn.grid(row=0, column=0, sticky=tk.E)

        # Status
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.parent, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=3, column=0, sticky=(tk.W, tk.E), padx=10, pady=(5, 10))

    def select_files(self):
        filenames = filedialog.askopenfilenames(
            title="Select Timesheet Files",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
        )
        if filenames:
            self.timesheet_paths = list(filenames)
            self.file_listbox.delete(0, tk.END)
            for filename in filenames:
                self.file_listbox.insert(tk.END, os.path.basename(filename))
            self.status_var.set(f"Selected {len(filenames)} file(s)")

    def clear_files(self):
        self.timesheet_paths = []
        self.file_listbox.delete(0, tk.END)
        self.status_var.set("Files cleared")

    def extract_data(self):
        if not self.timesheet_paths:
            messagebox.showwarning("No Files", "Please select timesheet files first.")
            return

        try:
            self.status_var.set("Extracting data from timesheets...")
            self.parent.update()

            for item in self.tree.get_children():
                self.tree.delete(item)

            results = self.extractor.extract_multiple_timesheets(self.timesheet_paths)

            if results['errors']:
                error_msg = "\n".join([f"• {e['file']}: {e['error']}" for e in results['errors']])
                messagebox.showwarning("Extraction Warnings", f"Some files had issues:\n\n{error_msg}")

            if not results['data']:
                messagebox.showwarning("No Data", "No timesheet data could be extracted.")
                self.status_var.set("No data extracted")
                return

            # Sort by name order
            self.extracted_data = self.extractor.sort_by_name_order(results['data'], self.name_order)

            # Populate tree
            for entry in self.extracted_data:
                hours = entry['hours']
                self.tree.insert("", tk.END, values=(
                    entry['name'],
                    entry['end_date'].strftime('%m/%d/%Y'),
                    f"{hours['Regular Hours']:.2f}",
                    f"{hours['Overtime 1 Hours']:.2f}",
                    f"{hours['Overtime 2 Hours']:.2f}",
                    f"{hours['Drive Hours']:.2f}",
                    f"{hours['Sick/PEL']:.2f}",
                    f"{hours['Vacation']:.2f}",
                    f"{hours['Holiday']:.2f}",
                    f"{hours['Non-Billable']:.2f}"
                ))

            success_msg = f"Extracted data for {len(self.extracted_data)} timesheet(s)"
            if results['errors']:
                success_msg += f" ({len(results['errors'])} error(s))"
            self.status_var.set(success_msg)
            messagebox.showinfo("Success", success_msg)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to extract data:\n{str(e)}")
            self.status_var.set("Error during extraction")

    def export_to_csv(self):
        if not self.extracted_data:
            messagebox.showwarning("No Data", "Please extract data from timesheets first.")
            return

        try:
            # Use the end date from the first timesheet for the filename
            if self.extracted_data:
                end_date = self.extracted_data[0]['end_date']
                ending_date_formatted = end_date.strftime('%m/%d/%Y')
                ending_date_filename = end_date.strftime('%Y%m%d')
            else:
                ending_date_formatted = datetime.now().strftime('%m/%d/%Y')
                ending_date_filename = datetime.now().strftime('%Y%m%d')

            # Prepare CSV data
            csv_data = []
            for entry in self.extracted_data:
                hours = entry['hours']
                csv_data.append({
                    'Ending': ending_date_formatted,
                    'Employee': entry['name'],
                    'Label': 'Hours',
                    'Hours_1': hours['Regular Hours'],
                    'Hours_2': hours['Overtime 1 Hours'],
                    'Hours_3': hours['Overtime 2 Hours'],
                    'Hours_4': hours['Drive Hours'],
                    'Hours_5': hours['Sick/PEL'],
                    'Hours_6': hours['Vacation'],
                    'Hours_7': hours['Holiday'],
                    'Hours_8': hours['Non-Billable']
                })

            df = pd.DataFrame(csv_data)
            default_filename = f"timesheet_export_{ending_date_filename}.csv"

            save_path = filedialog.asksaveasfilename(
                title="Save CSV File",
                defaultextension=".csv",
                initialfile=default_filename,
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
            )

            if save_path:
                df.to_csv(save_path, index=False)
                self.status_var.set(f"Exported to: {os.path.basename(save_path)}")
                messagebox.showinfo("Success", f"Timesheet data successfully exported to:\n{save_path}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to export data:\n{str(e)}")
            self.status_var.set("Error during export")


class MainApplication:
    """Main application with tabbed interface"""

    def __init__(self, root):
        self.root = root
        self.root.title("Payroll & Timesheet Data Extractor")
        self.root.geometry("950x750")

        # Configure root
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Create notebook (tabbed interface)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=5, pady=5)

        # Create tabs
        self.payroll_frame = ttk.Frame(self.notebook)
        self.timesheet_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.payroll_frame, text="Payroll PDF Extractor")
        self.notebook.add(self.timesheet_frame, text="Timesheet Extractor")

        # Initialize tabs
        self.payroll_tab = PayrollPDFTab(self.payroll_frame)
        self.timesheet_tab = TimesheetTab(self.timesheet_frame)


def main():
    """Main entry point"""
    root = tk.Tk()
    app = MainApplication(root)
    root.mainloop()


if __name__ == "__main__":
    main()
