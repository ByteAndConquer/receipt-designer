"""
ui/variables.py - Variable management UI panel
"""

from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .main_window import MainWindow


class VariableDialog(QtWidgets.QDialog):
    """Dialog for adding/editing a variable"""
    
    def __init__(self, parent=None, name: str = "", value: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Edit Variable" if name else "Add Variable")
        self.resize(400, 200)
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # Form
        form = QtWidgets.QFormLayout()
        
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setText(name)
        self.name_edit.setPlaceholderText("e.g., store_name, phone, email")
        if name:  # Editing existing - don't allow name change
            self.name_edit.setReadOnly(True)
        form.addRow("Variable Name:", self.name_edit)
        
        self.value_edit = QtWidgets.QTextEdit()
        self.value_edit.setPlainText(value)
        self.value_edit.setPlaceholderText("Variable value...")
        self.value_edit.setMaximumHeight(100)
        form.addRow("Value:", self.value_edit)
        
        layout.addLayout(form)
        
        # Help text
        help_label = QtWidgets.QLabel(
            "<small>Use {{var:variable_name}} in text elements to insert this variable's value.</small>"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        
        layout.addStretch()
        
        # Buttons
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
    
    def get_name(self) -> str:
        return self.name_edit.text().strip()
    
    def get_value(self) -> str:
        return self.value_edit.toPlainText().strip()


class VariablePanel(QtWidgets.QWidget):
    """Panel for managing template variables"""
    
    variables_changed = QtCore.Signal()
    
    def __init__(self, main_window: MainWindow, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._build_ui()
        self._refresh_list()
    
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Toolbar
        toolbar = QtWidgets.QHBoxLayout()
        
        btn_add = QtWidgets.QPushButton("Add")
        btn_add.setToolTip("Add new variable")
        btn_add.clicked.connect(self._add_variable)
        toolbar.addWidget(btn_add)
        
        btn_edit = QtWidgets.QPushButton("Edit")
        btn_edit.setToolTip("Edit selected variable")
        btn_edit.clicked.connect(self._edit_variable)
        toolbar.addWidget(btn_edit)
        
        btn_delete = QtWidgets.QPushButton("Delete")
        btn_delete.setToolTip("Delete selected variable")
        btn_delete.clicked.connect(self._delete_variable)
        toolbar.addWidget(btn_delete)
        
        toolbar.addStretch()
        
        layout.addLayout(toolbar)
        
        # Variable list
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._edit_variable)
        layout.addWidget(self.list_widget)
        
        # Info label
        info_label = QtWidgets.QLabel(
            "<small><b>System Variables:</b> {{date}}, {{time}}, {{datetime}}, "
            "{{year}}, {{month}}, {{day}}, {{weekday}}, {{id}}<br>"
            "<b>User Variables:</b> {{var:variable_name}}</small>"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
    
    def _refresh_list(self):
        """Refresh the variable list"""
        self.list_widget.clear()
        
        vm = self.main_window.template.variable_manager
        variables = vm.get_all_variables()
        
        for name, value in sorted(variables.items()):
            # Truncate long values for display
            display_value = value[:50] + "..." if len(value) > 50 else value
            item_text = f"{name} = {display_value}"
            
            item = QtWidgets.QListWidgetItem(item_text)
            item.setData(QtCore.Qt.UserRole, name)
            self.list_widget.addItem(item)
    
    def _add_variable(self):
        """Add a new variable"""
        dlg = VariableDialog(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            name = dlg.get_name()
            value = dlg.get_value()
            
            if not name:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid Name",
                    "Variable name cannot be empty."
                )
                return
            
            # Validate name format
            import re
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
                QtWidgets.QMessageBox.warning(
                    self,
                    "Invalid Name",
                    "Variable name must start with a letter or underscore,\n"
                    "and contain only letters, numbers, and underscores."
                )
                return
            
            vm = self.main_window.template.variable_manager
            vm.set_variable(name, value)
            self._refresh_list()
            self.variables_changed.emit()
            self.main_window.view.viewport().update()
    
    def _edit_variable(self):
        """Edit selected variable"""
        current = self.list_widget.currentItem()
        if not current:
            return
        
        name = current.data(QtCore.Qt.UserRole)
        vm = self.main_window.template.variable_manager
        value = vm.get_variable(name)
        
        dlg = VariableDialog(self, name, value)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            new_value = dlg.get_value()
            vm.set_variable(name, new_value)
            self._refresh_list()
            self.variables_changed.emit()
            self.main_window.view.viewport().update()
    
    def _delete_variable(self):
        """Delete selected variable"""
        current = self.list_widget.currentItem()
        if not current:
            return
        
        name = current.data(QtCore.Qt.UserRole)
        
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete Variable",
            f"Delete variable '{name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            vm = self.main_window.template.variable_manager
            vm.delete_variable(name)
            self._refresh_list()
            self.variables_changed.emit()
            self.main_window.view.viewport().update()