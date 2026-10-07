from .read import Read
from .write import Write
from .edit import Edit
from .glob import Glob
from .bash import Bash


def coding_tools(cwd):
    return [Read(cwd), Write(cwd), Edit(cwd), Glob(cwd), Bash(cwd)]
