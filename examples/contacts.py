"""Simple contacts TUI — an example of SuperModel + Textual.

Tracks first name, last name, and phone number. Supports list, add, update,
and delete. Uses an in-memory database (data lasts for the process only).

Setup (from the repo root)::

    pip install -e ".[examples]"
    python examples/contacts.py
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
)

from supermodel import Database, Model


class Contact(Model):
    """A person in the address book."""

    first_name: str = ""
    last_name: str = ""
    phone_number: str = ""


class ContactsApp(App[None]):
    """List, add, update, and delete contacts persisted with SuperModel."""

    TITLE = "Contacts"
    CSS = """
    Screen {
        layout: vertical;
    }

    #table {
        height: 1fr;
        margin: 1 1 0 1;
    }

    /* Hide row highlight after save/new; clicks still work with show_cursor on. */
    #table.no-highlight > .datatable--cursor {
        background: transparent;
        color: $foreground;
        text-style: none;
    }

    #table.no-highlight > .datatable--fixed-cursor {
        background: transparent;
        color: $foreground;
        text-style: none;
    }

    #form {
        height: auto;
        margin: 0 1 1 1;
        padding: 0 1;
        border: solid $primary;
    }

    #form > Horizontal {
        height: auto;
    }

    #form Label {
        width: 14;
        height: 3;
        content-align: left middle;
    }

    #form Input {
        width: 1fr;
    }

    #buttons {
        height: auto;
        align: left middle;
        margin-top: 1;
    }

    #buttons Button {
        margin-right: 1;
    }

    #status {
        height: 1;
        margin: 0 1 1 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("n", "new", "New"),
        Binding("escape", "new", "Clear", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._editing_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="table", cursor_type="row")
        with Vertical(id="form"):
            with Horizontal():
                yield Label("First name")
                yield Input(placeholder="Ada", id="first_name")
            with Horizontal():
                yield Label("Last name")
                yield Input(placeholder="Lovelace", id="last_name")
            with Horizontal():
                yield Label("Phone")
                yield Input(placeholder="555-0100", id="phone_number")
            with Horizontal(id="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Delete", variant="error", id="delete")
                yield Button("New", id="clear")
        yield Label("Select a row to edit, or fill the form and Save.", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_columns("First", "Last", "Phone")
        table.add_class("no-highlight")
        self.refresh_table()
        self.query_one("#first_name", Input).focus()

    def refresh_table(self) -> None:
        table = self.query_one("#table", DataTable)
        table.clear()
        for contact in Contact.select(order_by=["last_name", "first_name"]):
            table.add_row(
                contact.first_name,
                contact.last_name,
                contact.phone_number,
                key=str(contact.id),
            )
        table.refresh()

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Label).update(message)

    def _clear_form(self) -> None:
        self._editing_id = None
        self.query_one("#first_name", Input).value = ""
        self.query_one("#last_name", Input).value = ""
        self.query_one("#phone_number", Input).value = ""

    def _prepare_new_contact(self) -> None:
        """Clear the form and remove the table row highlight for a new entry."""
        self._clear_form()
        table = self.query_one("#table", DataTable)
        table.add_class("no-highlight")
        self.query_one("#first_name", Input).focus()

    def _load_form(self, contact: Contact) -> None:
        self._editing_id = contact.id
        self.query_one("#first_name", Input).value = contact.first_name
        self.query_one("#last_name", Input).value = contact.last_name
        self.query_one("#phone_number", Input).value = contact.phone_number

    def _read_form(self) -> dict:
        return {
            "first_name": self.query_one("#first_name", Input).value.strip(),
            "last_name": self.query_one("#last_name", Input).value.strip(),
            "phone_number": self.query_one("#phone_number", Input).value.strip(),
        }

    def action_new(self) -> None:
        self._prepare_new_contact()
        self._set_status("New contact — fill the form and Save.")

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        # Refresh/save move the cursor and post RowHighlighted while focus is
        # still on the form. Only load a contact when the user focuses the table
        # (click or keyboard).
        if not event.data_table.has_focus:
            event.data_table.add_class("no-highlight")
            return
        if event.row_key is None or event.row_key.value is None:
            return

        event.data_table.remove_class("no-highlight")
        contact = Contact.get(str(event.row_key.value))
        self._load_form(contact)
        self._set_status(f"Editing {contact.first_name} {contact.last_name}.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save_contact()
        elif event.button.id == "delete":
            self._delete_contact()
        elif event.button.id == "clear":
            self.action_new()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._save_contact()

    def _save_contact(self) -> None:
        values = self._read_form()

        if not values["first_name"] and not values["last_name"]:
            self._set_status("Enter at least a first or last name.")
            return

        if self._editing_id is None:
            # Insert: id is None → save() creates a new row with a UUIDv7.
            Contact().set(values).save()
            self._set_status("Contact added.")
        else:
            # Update: load by id, set fields, save() writes the existing row.
            Contact.get(self._editing_id).set(values).save()
            self._set_status("Contact updated.")

        self.refresh_table()
        self._prepare_new_contact()

    def _delete_contact(self) -> None:
        if self._editing_id is None:
            self._set_status("Select a contact to delete.")
            return

        Contact.get(self._editing_id).remove()
        self.refresh_table()
        self._prepare_new_contact()
        self._set_status("Contact deleted.")


def main() -> None:
    Database().path = ":memory:"
    ContactsApp().run()


if __name__ == "__main__":
    main()
