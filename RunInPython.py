import gedit
import gtk

import sys
import select

import os
import subprocess

import gobject

import time

from threading import Thread
from threading import Timer

ui_string = """<ui>
  <menubar name="MenuBar">
    <menu name="ToolsMenu" action="Tools">
      <placeholder name="ToolsOps_2">
        <menuitem name="ToolRunInPython" action="ToolRunInPython"/>
        <menuitem name="ToolRunInPython_Reset" action="ToolRunInPython_Reset"/>
      </placeholder>
    </menu>
  </menubar>
</ui>
"""

class OutputArea(gtk.HBox):
    def __init__(self, geditwindow):
        gtk.HBox.__init__(self)
        
        self.geditwindow = geditwindow
        
        # Create a ListStore for the output we'll receive from the Python interpreter
        self.output_data = gtk.ListStore(str)
        
        # Create a TreeView (we'll use it just as a list though) for the output data
        self.output_list = gtk.TreeView(self.output_data)
        
        # Create a cell for the list
        cell = gtk.TreeViewColumn("Console Output")

        # Add the cell to the TreeView
        self.output_list.append_column(cell)
        
        # Create a text renderer for our cell
        text_renderer = gtk.CellRendererText()
        
        # Add that text renderer to the cell
        cell.pack_start(text_renderer, True)
        
        # Set it to text
        cell.add_attribute(text_renderer, "text", 0)
        
        # Create a scrolled window for the TreeView and add the TreeView to that scrolled window.
        scrolled_window = gtk.ScrolledWindow()
        scrolled_window.add(self.output_list)
        
        # Add the scrolled window to this HBox
        self.pack_start(scrolled_window)
        
        # Show everything
        self.show_all()

class PluginHelper:
    def __init__(self, plugin, window):
        self.window = window
        self.plugin = plugin
        
        self.process = None # Store the process ID in this variable when we launch it
        self.stdout_text = None
        
        self.pipe = None
        
        self.insert_menu_item(window)
        
        # Add an idling function to monitor whether we are viewing
        # an existing file that we can run in the Python interpreter.
        self.idle_id = gobject.timeout_add(100, self.monitor_document)
        
        # We'll keep track of the new process (checking for new input)
        # in a separate id.
        self.idle_id_new_process = None

    def deactivate(self):        
        self.remove_menu_item()
        
        self.window = None
        self.plugin = None
        self.action_group = None
        
    def update_ui(self):
        return True
        
    def insert_menu_item(self, window):
        manager = self.window.get_ui_manager()
        
        self.action_group = gtk.ActionGroup("PluginActions")
        
        # Create an action for the "Run in python" menu option
        # and set it to call the "run_document_in_python" function.
        self.run_in_python_action = gtk.Action(name="ToolRunInPython", label="Run Document in Python", tooltip="Run the current document through the Python interpreter", stock_id=gtk.STOCK_REFRESH)
        self.run_in_python_action.connect("activate", self.run_document_in_python)

        # Create an action to allow the user to clear the contents of the bottom panel.
        self.run_in_python_reset_action = gtk.Action(name="ToolRunInPython_Reset", label="Clear Run In Python output", tooltip="Clear the contents of the bottom panel", stock_id = None)
        self.run_in_python_reset_action.connect("activate", lambda unused_param: self.output_area.output_data.clear())
        
        # Add the action with Ctrl + F5 as its keyboard shortcut.
        self.action_group.add_action_with_accel(self.run_in_python_action, "<Ctrl>F5")
        self.action_group.add_action_with_accel(self.run_in_python_reset_action, "<Ctrl><Shift>F5")
        
        # Add the action group.
        manager.insert_action_group(self.action_group, -1)
        
        # Add the item to the "Tools" menu.
        self.ui_id = manager.add_ui_from_string(ui_string)
        
        # Get the bottom panel.
        panel = window.get_bottom_panel()
        
        # Create an output area object (HBox) where we'll store the Python interpreter's output.
        self.output_area = OutputArea(window)
        
        # Add the item to the panel.
        panel.add_item(self.output_area, "Output", gtk.Image())
        
    def remove_menu_item(self):
        # Remove our monitoring function
        gobject.source_remove(self.idle_id)
        
        # Remove the idle function that monitors the new process if necessary
        if (self.idle_id_new_process):
            gobject.source_remove(self.idle_id_new_process)
        
        manager = self.window.get_ui_manager()
        
        manager.remove_ui(self.ui_id)
        self.action_group = None
        
        panel = self.window.get_bottom_panel()
        
        panel.remove_item(self.output_area)
        
    def run_document_in_python(self, action):
        path = self.window.get_active_document().get_uri().replace("file://", "")
        path = path.replace("%20", " ")

        basename = os.path.basename(path)
        
        # Create a pipe
        self.pipe, w = os.pipe()
        
        # Set the working directory to the current document's path
        os.chdir(path.rstrip(basename))
        
        # Fork the process
        id = os.fork()
        self.process_id = id # Store the new process's ID
        
        # New Processs
        if (not id):
            # Override the standard output and error output to go to the pipe we made
            os.dup2(w, 1)
            os.dup2(w, 2)
            
            # Close the read side of the pipe for this process
            os.close(self.pipe)
            
            # Replace the current process
            os.execvp('/usr/bin/python', ['/usr/bin/python', '-u', path ])

        # Existing Process
        else:
            # Override the standard input of the existing process with the read side
            # of the pipe that we made.
            os.dup2(self.pipe, 0)
            
            # Close the write side of the pipe for this process
            os.close(w)
            
            # Set the standard input file object to read our input pipe
            sys.stdin = os.fdopen(self.pipe, "r", 0)
            
            # Add a function that will monitor the pipe for new data
            self.idle_id_new_process = gobject.idle_add(self.timer_function)
            
            # Disable the "Run document in Python" menu option until the process ends
            self.action_group.set_sensitive(False)
        
    def timer_function(self):
        # See if we have any new data.  Timeout after 0.001 seconds.
        r, w, x = select.select([self.pipe], [], [], 0.001)
        
        # Do we have any data?
        if (r):
            
            # Get rid of the newline character at the end.
            line = sys.stdin.readline().rstrip("\n")
            
            # Do we have any data?
            if (line != ""):
                # Add the new data to the TreeView we made
                self.output_area.output_data.append( (line,) )
                
                # Scroll to the end of the TreeView
                self.output_area.output_list.set_cursor(len(self.output_area.output_data) - 1)
                
        # We're going to see if the new process we created is still running.
        data = os.popen("ps -p %d" % self.process_id).read()
        
        if (data.split("\n")[1] == '' or data.split("\n")[1].endswith("<defunct>")):
            line = sys.stdin.read().rstrip("\n")
            
            # The process has ended; let's get whatever data remains.
            if (line != ''):
                lines = line.split("\n")

                for each in lines:                
                    self.output_area.output_data.append( (each,) )
                    
                # Scroll to the end of the output area
                self.output_area.output_list.set_cursor(len(self.output_area.output_data) - 1)

            # Wait for the child process to officially finish
            # so that it doesn't remain as a ZOMBIE!!!
            os.waitpid(self.process_id, 0)
            
            # We have no process to track now
            self.process_id = 0
            
            # Re-enable the menu item
            self.action_group.set_sensitive(True)

            self.idle_id_new_process = None
            
            # return False to stop this idle function
            return False

        return True
            
    # See if the current document exists on the user's computer...
    def monitor_document(self):
        active_document = self.window.get_active_document()
        
        if (active_document):
            if (active_document.is_untitled()):
                self.run_in_python_action.set_sensitive(False)
            else:
                self.run_in_python_action.set_sensitive(True)
                
        else:
            self.run_in_python_action.set_sensitive(False)
            
        return True

class RunInPython(gedit.Plugin):
    def __init__(self):
        gedit.Plugin.__init__(self)
        self.instances = {}
        
    def activate(self, window):
        self.instances[window] = PluginHelper(self, window)
        
    def deactivate(self, window):
        #print "Deactivating..."
        self.instances[window].deactivate()
        
    def update_ui(self, window):
        self.instances[window].update_ui()
