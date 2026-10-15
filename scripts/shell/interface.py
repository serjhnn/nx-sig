# interface: what a command module implements
#
# every scripts/shell/*_cmd.py has a Commands subclass
# for one kind of data (trade, rule, ladder, ...).
# commands.py collects them at start and calls their
# actions; a module implements only the actions it
# supports, see CLI_BLUEPRINT.md
#
#   Commands.ACTIONS     the action words
#   Commands(shell)      one instance per shell
#   .supports(action)    True if the module has it
#   .actions()           the actions it has
#   .complete(action, args)
#                        completion options per argument
#   .tasks()             its rows for 'ls tasks'


class Commands:
    """One kind of data the shell works on."""

    ACTIONS = ("ls", "add", "rm", "run", "stop")

    # singular: "ladder"
    name = ""
    # used after ls: "ladders"
    plural = ""
    # where the module comes in 'ls tasks' and in the
    # lists of objects, lowest first
    order = 100

    # the actions take the rest of the command line as
    # text, like cmd.Cmd's do_<command>:
    #   def ls(self, arg): ...
    #   def add(self, arg): ...
    #   def rm(self, arg): ...
    #   def run(self, arg): ...
    #   def stop(self, arg): ...

    def __init__(self, shell):
        self.shell = shell

    def supports(self, action):
        return action in self.ACTIONS and callable(
            getattr(self, action, None)
        )

    def actions(self):
        return [a for a in self.ACTIONS if self.supports(a)]

    def complete(self, action, args):
        """the completion options of each argument of
        action, one list per position; args are the
        words typed after the object so far"""
        return []

    def tasks(self):
        """the 'ls tasks' rows of the module's running
        background tasks"""
        return []
