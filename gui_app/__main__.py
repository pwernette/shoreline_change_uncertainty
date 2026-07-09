"""Entry point: python -m gui_app"""
from gui_app.app import ShorelineUncertaintyApp


def main():
    app = ShorelineUncertaintyApp()
    app.mainloop()


if __name__ == "__main__":
    main()
