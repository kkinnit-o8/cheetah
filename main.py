import ollama
import time
import threading
from pynput import keyboard
from pynput.keyboard import Controller, Key

kb = Controller()

IGNORED_KEYS = {
    Key.shift, Key.shift_r,
    Key.ctrl, Key.ctrl_r,
    Key.alt, Key.alt_r, Key.alt_gr,
    Key.caps_lock, Key.cmd, Key.cmd_r,
    Key.up, Key.down, Key.left, Key.right,
    Key.home, Key.end, Key.page_up, Key.page_down,
    Key.f1, Key.f2, Key.f3, Key.f4, Key.f5, Key.f6,
    Key.f7, Key.f8, Key.f9, Key.f10, Key.f11, Key.f12, Key.enter
}

def fake_type(text, delay):
    chars_list = list(text)
    total = len(chars_list)
    typed = [0]
    stopped = [False]
    last_time = [0]
    injecting = [False]
    done_event = threading.Event
    COOLDOWN = 0.05

    def type_char(ch):
        injecting[0] = True
        # Delete the key the user actually pressed
        kb.press(Key.backspace)
        kb.release(Key.backspace)
        time.sleep(0.02)
        if delay > 0:
            time.sleep(delay)
        # Type the real character
        kb.type(ch)
        time.sleep(0.02)
        injecting[0] = False

    def on_press(key):
        # Ignore our own injected keystrokes
        if injecting[0]:
            return

        if key == Key.esc:
            stopped[0] = True
            done_event.set()
            return False

        if key in IGNORED_KEYS:
            return

        # Ignore backspace (it's us cleaning up)
        if key == Key.backspace:
            return

        now = time.time()
        if now - last_time[0] < COOLDOWN:
            return
        last_time[0] = now

        if typed[0] < total:
            ch = chars_list[typed[0]]
            typed[0] += 1
            threading.Thread(target=type_char, args=(ch,), daemon=True).start()

        if typed[0] >= total:
            done_event.set()
            return False

    print("\n✓ Response ready! Switch to your target window, then start pressing keys.")
    print("  Press ESC to stop.\n")

    # suppress=False so injected chars actually reach the window
    with keyboard.Listener(on_press=on_press, suppress=False) as listener:
        done_event.wait()

    if stopped[0]:
        print("\n⏹ Stopped early.")
    else:
        print("\n✓ Done typing!")


def main():
    print("\n=== Ollama Fake Typer ===\n")

    while True:
        mode = input("Would you like [code] or [text]? ").strip().lower()
        if mode in ("code", "text"):
            break
        print("Please enter 'code' or 'text'.")

    model = "deepseek-coder:6.7b" if mode == "code" else "llama3"
    print(f"\nUsing model: {model}")
    print("Pulling model (if not already available)...")
    try:
        ollama.pull(model)
    except Exception as e:
        print(f"Warning: Could not pull model: {e}")

    print()
    prompt = input("Enter your prompt:\n> ").strip()
    if not prompt:
        print("No prompt entered. Exiting.")
        return

    print("\nTyping speed:")
    print("  [1] Slow    (~120ms delay, human-like)")
    print("  [2] Medium  (~40ms delay, fast typist)")
    print("  [3] Fast    (no delay, instant per keypress)")
    while True:
        speed = input("Choose speed [1/2/3]: ").strip()
        if speed in ("1", "2", "3"):
            break
        print("Please enter 1, 2, or 3.")
    delay = {"1": 0.12, "2": 0.04, "3": 0.0}[speed]

    print(f"\nQuerying {model}... (this may take a moment)\n")
    try:
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": f"{prompt} respond with only the {mode} output, no explanations or commentary"}]
        )
        output_text = response["message"]["content"]
    except Exception as e:
        print(f"Error querying model: {e}")
        return

    print(f"Got {len(output_text)} characters ready.")
    fake_type(output_text, delay)

if __name__ == "__main__":
    main()