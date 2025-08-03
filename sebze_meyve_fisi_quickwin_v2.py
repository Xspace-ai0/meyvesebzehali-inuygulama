import os
import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import datetime
import platform
import subprocess
import logging
from pathlib import Path
import unicodedata
import difflib
import pathlib

# --- Configuration / Sabitler ---
CUSTOMER_FILE = Path("customers.json")
LOG_FILE = Path("uygulama.log")
logging.basicConfig(filename=str(LOG_FILE), level=logging.ERROR,
                    format="%(asctime)s [%(levelname)s] %(message)s", encoding='utf-8')

# --- Veri modeli ---

from dataclasses import dataclass
from typing import List

@dataclass
class Customer:
    name: str
    phone: str = ''
    address: str = ''

    def to_dict(self) -> dict:
      """Return a dictionary representation of the customer."""
        return {'name': self.name, 'phone': self.phone, 'address': self.address}

    @classmethod
    def from_dict(cls, data: dict) -> "Customer":
      """Create a Customer instance from a dictionary."""
        return cls(
            name=data.get('name', ''),
            phone=data.get('phone', ''),
            address=data.get('address', '')
        )



def _normalize_for_comparison(name: str) -> str:
  """Normalize a name for case-insensitive comparisons."""
    # Unicode normalize, strip extra spaces, casefold for comparison (handles Turkish case more robustly)
    name = unicodedata.normalize("NFKC", name)
    name = " ".join(name.strip().split())
    return name.casefold()

def _format_for_display(name: str) -> str:
    """Return a display-friendly title-cased name."""
    # Title-case with minimal Turkish-specific handling for initial i
    def turkish_title(word: str) -> str:
      """Title-case a single word with Turkish-specific handling."""
        w = word.strip().lower()
        if w.startswith("i"):
            return "İ" + w[1:]
        return w.capitalize()
    return " ".join(turkish_title(w) for w in name.strip().split())


def _find_customer_by_name(customers, name: str):
   """Search for a customer by name using normalized and fuzzy matching."""
    if not name:
        return None
    key = _normalize_for_comparison(name)
    for c in customers:
        if _normalize_for_comparison(c.name) == key:
            return c
    candidates = { _normalize_for_comparison(c.name): c for c in customers }
    close = difflib.get_close_matches(key, list(candidates.keys()), n=1, cutoff=0.7)
    if close:
        return candidates[close[0]]
    return None


def load_customers() -> list[Customer]:
  """Load customers from disk, returning a list of Customer objects."""
    if CUSTOMER_FILE.exists():
        try:
            with CUSTOMER_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [Customer.from_dict(item) for item in data]
        except Exception:
            logging.exception('load_customers failed')
    return []

def save_customers(customers: list[Customer]) -> None:
  """Persist the list of customers to disk."""
    try:
        with CUSTOMER_FILE.open('w', encoding='utf-8') as f:
            json.dump([c.to_dict() for c in customers], f, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception('save_customers failed')

class ReceiptApp:
    """Main application window for generating receipts."""
    ROLE_VAT_MAP = {
        'Pazarcı Esnafı': 0.02,
        'Hal İçi / Ortacı': 0.01
    }

    def __init__(self, master):
      """Initialize the GUI components and load initial data."""
        self.master = master
        master.title('Sebze-Meyve Fiş Uygulaması (Sade)')

        style = ttk.Style(master)
        style.configure('Bold.TLabelframe.Label', font=('Segoe UI', 10, 'bold'), foreground='darkblue')

        self.customers = load_customers()
        save_customers(self.customers)  # ensure file exists and is normalized

        # Variables
        self.customer_name_var = tk.StringVar()
        self.item_type_var = tk.StringVar()
        self.piece_count_var = tk.StringVar()
        self.weight_var = tk.StringVar()
        self.price_per_kg_var = tk.StringVar()
        self.total_var = tk.StringVar(value='0.00')
        self.role_var = tk.StringVar(value='Pazarcı Esnafı')
        self.new_customer_var = tk.StringVar()
        self.category_var = tk.StringVar(value='MEYVE')
        self.subitem_var = tk.StringVar()

        self.fruits = ['ŞEFTALİ', 'NEKTARİ', 'PORTAKAL', 'MANDALİNA', 'ELMA', 'NAR', 'ÇİLEK', 'MUZ', 'DİĞER']
        self.vegetables = ['FASULYE', 'DOMATES', 'DİĞER']

        # HEADER
        header = ttk.Frame(master, padding=(8, 8))
        header.pack(fill='x', padx=5, pady=3)

        # Customer panel
        customer_frame = ttk.LabelFrame(header, text='Müşteri Bilgisi', padding=6, style='Bold.TLabelframe')
        customer_frame.grid(row=0, column=0, sticky='nsew', padx=4, pady=2)
        customer_frame.columnconfigure(1, weight=1)
        customer_frame.rowconfigure(1, weight=1)

        ttk.Label(customer_frame, text='Müşteri Adı:').grid(row=0, column=0, sticky='e', padx=2, pady=2)
        name_entry = ttk.Entry(customer_frame, textvariable=self.customer_name_var, width=25)
        name_entry.grid(row=0, column=1, sticky='ew', padx=2, pady=2)
        name_entry.bind('<KeyRelease>', self._on_name_typing)

        ttk.Label(customer_frame, text='Müşteri Listesi:').grid(row=1, column=0, sticky='ne', padx=2, pady=4)
        self.listbox = tk.Listbox(customer_frame, height=6, activestyle='dotbox')
        self.listbox_scrollbar = ttk.Scrollbar(customer_frame, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=self.listbox_scrollbar.set)
        self.listbox.grid(row=1, column=1, sticky='nsew', padx=(2, 0), pady=4)
        self.listbox_scrollbar.grid(row=1, column=2, sticky='ns', padx=(0, 2), pady=4)
        self._refresh_listbox()
        self.listbox.bind('<<ListboxSelect>>', self._on_listbox_select)
        self.listbox.bind('<MouseWheel>', self._on_mousewheel)
        self.listbox.bind('<Button-4>', self._on_mousewheel)
        self.listbox.bind('<Button-5>', self._on_mousewheel)

        add_customer_frame = ttk.Frame(customer_frame)
        add_customer_frame.grid(row=2, column=1, sticky='w', padx=2, pady=(2, 4))
        ttk.Entry(add_customer_frame, textvariable=self.new_customer_var, width=15).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(add_customer_frame, text='Müşteri Ekle', command=self._add_new_customer).grid(row=0, column=1)
        ttk.Button(add_customer_frame, text='Müşteri Sil', command=self._remove_selected_customer).grid(row=0, column=2, padx=(6, 0))

        # Item panel
        item_frame = ttk.LabelFrame(header, text='Ürün Seçimi', padding=6, style='Bold.TLabelframe')
        item_frame.grid(row=0, column=1, sticky='nsew', padx=4, pady=2)
        for i in range(4):
            item_frame.columnconfigure(i, weight=1)
        ttk.Label(item_frame, text='Kategori:').grid(row=0, column=0, sticky='e', padx=2, pady=2)
        kat_frame = ttk.Frame(item_frame)
        kat_frame.grid(row=0, column=1, sticky='w', padx=2, pady=2)
        for val in ['MEYVE', 'SEBZE']:
            ttk.Radiobutton(kat_frame, text=val, variable=self.category_var, value=val,
                            command=self._on_category_changed).pack(side='left', padx=4)
        ttk.Label(item_frame, text='Alt Cinsi:').grid(row=0, column=2, sticky='e', padx=2, pady=2)
        self.subitem_combobox = ttk.Combobox(item_frame, textvariable=self.subitem_var, state='readonly',
                                             values=self.fruits, width=18)
        self.subitem_combobox.grid(row=0, column=3, sticky='w', padx=2, pady=2)
        self.subitem_combobox.bind('<<ComboboxSelected>>', self._on_subitem_selected)
        ttk.Label(item_frame, text='Malın Cinsi:').grid(row=1, column=0, sticky='e', padx=2, pady=4)
        item_entry = ttk.Entry(item_frame, textvariable=self.item_type_var, width=30, state='readonly')
        item_entry.grid(row=1, column=1, columnspan=3, sticky='w', padx=2, pady=4)

        # Role panel
        role_frame = ttk.LabelFrame(header, text='İşlem Bilgisi', padding=6, style='Bold.TLabelframe')
        role_frame.grid(row=0, column=2, sticky='nsew', padx=4, pady=2)
        ttk.Label(role_frame, text='Müşteri Türü:').grid(row=0, column=0, sticky='w', padx=2, pady=2)
        self.role_selector = ttk.Combobox(role_frame, textvariable=self.role_var, state='readonly',
                                          values=list(self.ROLE_VAT_MAP.keys()), width=20)
        self.role_selector.grid(row=0, column=1, sticky='w', padx=2, pady=2)
        self.role_selector.bind('<<ComboboxSelected>>', lambda e: self.calculate_total())

        # MAIN FORM
        form_wrapper = ttk.Frame(master)
        form_wrapper.pack(fill='both', expand=True, padx=5, pady=(4, 2))

        ttk.Label(form_wrapper, text='Parça Adedi (kasa):').grid(row=0, column=0, sticky='e', padx=5, pady=6)
        ttk.Entry(form_wrapper, textvariable=self.piece_count_var, width=12).grid(row=0, column=1, sticky='w', padx=5, pady=6)
        ttk.Label(form_wrapper, text='Kilo (kg):').grid(row=1, column=0, sticky='e', padx=5, pady=6)
        ttk.Entry(form_wrapper, textvariable=self.weight_var, width=12).grid(row=1, column=1, sticky='w', padx=5, pady=6)
        ttk.Label(form_wrapper, text='Birim Fiyat (TL/kg):').grid(row=2, column=0, sticky='e', padx=5, pady=6)
        ttk.Entry(form_wrapper, textvariable=self.price_per_kg_var, width=12).grid(row=2, column=1, sticky='w', padx=5, pady=6)
        ttk.Label(form_wrapper, text='Toplam Tutar (KDV dahil):').grid(row=3, column=0, sticky='e', padx=5, pady=6)
        tk.Entry(form_wrapper, textvariable=self.total_var, width=20, state='readonly', foreground='blue').grid(row=3, column=1, sticky='w', padx=5, pady=6)

        for var in (self.weight_var, self.price_per_kg_var, self.role_var):
            var.trace_add('write', lambda *args: self.calculate_total())

        # Bottom actions
        action_frame = ttk.Frame(master, padding=6)
        action_frame.pack(fill='x', padx=5, pady=8)
        ttk.Button(action_frame, text='Fişi Yazdır / Kaydet', command=self.print_receipt).pack(side='left', padx=6)
        ttk.Button(action_frame, text='Çıkış', command=master.quit).pack(side='right', padx=6)

        # Initial values
        self._on_category_changed()

    def _refresh_listbox(self):
       """Populate the listbox with customers sorted alphabetically."""
        self.listbox.delete(0, tk.END)
        for c in sorted(self.customers, key=lambda c: c.name.lower()):
            self.listbox.insert(tk.END, c.name)

    def _on_listbox_select(self, event):
          """Insert the selected customer name into the entry field."""
        sel = self.listbox.curselection()
        if sel:
            name = self.listbox.get(sel[0])
            self.customer_name_var.set(name)

    def _add_new_customer(self):
        """Add a new customer to the list and save it."""
        raw = self.new_customer_var.get()
        normalized = _normalize_for_comparison(raw)
        if not normalized:
            messagebox.showinfo('Bilgi', 'Müşteri adı boş olamaz.')
            return
        existing_keys = [_normalize_for_comparison(c.name) for c in self.customers]
        if normalized in existing_keys:
            messagebox.showinfo('Bilgi', 'Bu müşteri zaten mevcut.')
            return
        display_name = _format_for_display(raw)
        self.customers.append(Customer(name=display_name))
        save_customers(self.customers)
        self.new_customer_var.set('')
        self._refresh_listbox()

    def _remove_selected_customer(self):
       """Delete the selected customer after confirmation."""
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo('Uyarı', 'Silmek için bir müşteri seçin.')
            return
        name = self.listbox.get(sel[0])
        if messagebox.askyesno('Sil', f"'{name}' müşterisini silmek istiyor musunuz?"):
            self.customers = [c for c in self.customers if _normalize_for_comparison(c.name) != _normalize_for_comparison(name)]
            save_customers(self.customers)
            self._refresh_listbox()
            if self.customer_name_var.get() == name:
                self.customer_name_var.set('')

    def _on_name_typing(self, event):
        """Filter the customer list based on typed characters."""
        typed_raw = self.customer_name_var.get()
        norm_typed = _normalize_for_comparison(typed_raw)
        matches = set()
        # substring match (normalized)
        for c in self.customers:
            if norm_typed and norm_typed in _normalize_for_comparison(c.name):
                matches.add(c.name)
        # fuzzy close matches
        normalized_map = { _normalize_for_comparison(c.name): c.name for c in self.customers }
        if norm_typed:
            close = difflib.get_close_matches(norm_typed, list(normalized_map.keys()), n=10, cutoff=0.6)
            for key in close:
                matches.add(normalized_map[key])
        self.listbox.delete(0, tk.END)
        for name in sorted(matches, key=lambda x: x.lower()):
            self.listbox.insert(tk.END, name)
        if not typed_raw:
            self._refresh_listbox()

    def _on_mousewheel(self, event):
         """Scroll the listbox using mouse wheel events."""
        try:
            if event.delta:
                direction = -1 if event.delta > 0 else 1
                self.listbox.yview_scroll(direction, 'units')
        except AttributeError:
            if event.num == 4:
                self.listbox.yview_scroll(-1, 'units')
            elif event.num == 5:
                self.listbox.yview_scroll(1, 'units')

    def _on_category_changed(self, event=None):
         """Adjust subitem options when the category selection changes."""
        cat = self.category_var.get()
        if cat == 'MEYVE':
            self.subitem_combobox.configure(values=self.fruits, state='readonly')
            self.subitem_var.set(self.fruits[0])
        elif cat == 'SEBZE':
            self.subitem_combobox.configure(values=self.vegetables, state='readonly')
            self.subitem_var.set(self.vegetables[0])
        self._apply_subitem_to_item()

    def _on_subitem_selected(self, event=None):
      """Handle selection of a predefined subitem."""
        self._apply_subitem_to_item()

    def _apply_subitem_to_item(self):
              """Update the item type based on current subitem value."""
        val = self.subitem_var.get()
        if val == 'DİĞER':
            custom = simpledialog.askstring('Diğer Alt Cinsi', 'Alt cinsi giriniz:')
            if custom:
                self.item_type_var.set(custom.upper())
        elif val:
            self.item_type_var.set(val)

    
    def _parse_number(self, value: str) -> float:
      """Convert a localized string to a float value."""
        if not value:
            return 0.0
        try:
            return float(value.replace(',', '.'))
        except ValueError:
            return 0.0

    def calculate_total(self) -> None:
         """Recalculate the total price including VAT."""
        try:
            weight = self._parse_number(self.weight_var.get())
            price = self._parse_number(self.price_per_kg_var.get())
            net_total = weight * price
            vat_rate = self.ROLE_VAT_MAP.get(self.role_var.get(), 0.0)
            total_with_vat = net_total + net_total * vat_rate
            self.total_var.set(f"{total_with_vat:.2f}".replace('.', ',') + ' TL')
        except Exception:
            logging.exception('calculate_total failed')

    def _generate_receipt_text(self, customer, item_type, piece_count, weight, price, vat_rate):
      """Create the plain text content of the receipt."""
        net_total = weight * price
        vat_amount = net_total * vat_rate
        total_with_vat = net_total + vat_amount
        return (
            '=== SEBZE-MEYVE FİŞİ ===\n'
            f"Tarih: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Müşteri Türü: {self.role_var.get()}\n"
            f"Müşteri Adı: {customer.name if customer else ''}\n"
            f"Malın Cinsi: {item_type}\n"
            f"Parça Adedi: {piece_count}\n"
            f"Kilo: {weight:.2f} kg\n"
            f"Birim Fiyat: {price:.2f}\n"
            f"Net Tutar: {net_total:.2f}\n"
            f"KDV (%{vat_rate*100:.0f}): {vat_amount:.2f}\n"
            f"Toplam: {total_with_vat:.2f}\n"
        )

    def _print_to_printer(self, file_path):
      """Send the file to the system print queue."""
        printed = False
        if platform.system() == 'Windows':
            try:
                os.startfile(file_path, 'print')
                printed = True
            except Exception:
                pass
        else:
            try:
                subprocess.run(['lpr', file_path], check=True)
                printed = True
            except Exception:
                pass
        return printed

    def clear_form(self):
       """Reset all form fields to their defaults."""
        self.customer_name_var.set('')
        self.item_type_var.set('')
        self.piece_count_var.set('')
        self.weight_var.set('')
        self.price_per_kg_var.set('')
        self.total_var.set('0.00')
        if self.category_var.get() == 'MEYVE':
            self.category_var.set('MEYVE')
            self.subitem_var.set(self.fruits[0])
        else:
            self.category_var.set('SEBZE')
            self.subitem_var.set(self.vegetables[0])
        # Bilgi mesajı
        messagebox.showinfo('Temizlendi', 'Form sıfırlandı.')

    
    def _write_receipt_atomic(self, path: Path, content: str) -> None:
      """Atomically write receipt content to a file."""
        tmp = path.with_suffix('.tmp')
        try:
            tmp.write_text(content, encoding='utf-8')
            tmp.replace(path)
        except Exception:
            logging.exception("Atomic write of receipt failed")
            raise

    def _do_print(self, file_path: pathlib.Path):
      """Print the given file using platform-specific commands."""
        try:
            if platform.system() == 'Windows':
                os.startfile(str(file_path), 'print')
            else:
                subprocess.run(['lpr', str(file_path)], check=True, capture_output=True, text=True, timeout=15)
        except Exception:
            logging.exception("Printing failed")

    def _clear_form_after_print(self):
       """Clear specific fields after successful printing."""
        self.piece_count_var.set('')
        self.weight_var.set('')
        self.price_per_kg_var.set('')
        self.total_var.set('0.00')

    
    def print_receipt(self):
         """Validate input, save the receipt, and send it to the printer."""
        try:
            # Kısa vadeli validasyonlar
            customer_name = self.customer_name_var.get().strip()
            if not customer_name:
                messagebox.showwarning('Eksik', 'Müşteri adı boş olamaz.')
                return
            weight = self._parse_number(self.weight_var.get())
            price = self._parse_number(self.price_per_kg_var.get())
            if weight <= 0:
                messagebox.showwarning('Geçersiz', 'Kilo pozitif bir sayı olmalı.')
                return
            if price <= 0:
                messagebox.showwarning('Geçersiz', 'Birim fiyat pozitif bir sayı olmalı.')
                return

            customer = _find_customer_by_name(self.customers, customer_name)
            if customer is None:
                customer_display = _format_for_display(customer_name)
                customer = Customer(name=customer_display)
            vat_rate = self.ROLE_VAT_MAP.get(self.role_var.get(), 0.0)
            receipt_text = self._generate_receipt_text(
                customer,
                self.item_type_var.get(),
                self.piece_count_var.get(),
                weight,
                price,
                vat_rate
            )

            # Kaydetme yeri: önceki dizin varsa sor, yoksa seçtir
            if hasattr(self, 'last_save_dir') and self.last_save_dir:
                use_prev = messagebox.askyesno('Kaydetme yeri', f'Önceki konuma kaydetmek istiyor musunuz?\n{self.last_save_dir}')
                if use_prev:
                    save_dir = Path(self.last_save_dir)
                    filename = f"fis_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
                    save_path = save_dir / filename
                else:
                    chosen = filedialog.asksaveasfilename(defaultextension='.txt',
                        initialfile=f"fis_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt",
                        filetypes=[('Text Files', '*.txt')], title='Fişi Kaydet')
                    if not chosen:
                        return
                    save_path = Path(chosen)
                    self.last_save_dir = str(save_path.parent)
            else:
                chosen = filedialog.asksaveasfilename(defaultextension='.txt',
                    initialfile=f"fis_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt",
                    filetypes=[('Text Files', '*.txt')], title='Fişi Kaydet')
                if not chosen:
                    return
                save_path = Path(chosen)
                self.last_save_dir = str(save_path.parent)

            # Kaydet
            self._write_receipt_atomic(save_path, receipt_text)
            self._do_print(save_path)
            messagebox.showinfo('Tamam', f"Fiş kaydedildi: {save_path}")
            self._clear_form_after_print()
        except Exception:
            logging.exception('print_receipt failed during overall process')
            messagebox.showerror('Hata', 'Fiş oluşturulurken beklenmedik bir hata oluştu. Lütfen tekrar deneyin.')


def main():
     """Start the receipt application."""
    root = tk.Tk()
    ReceiptApp(root)
    root.mainloop()

if __name__ == '__main__':
    main()
