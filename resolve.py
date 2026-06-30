import re

with open("react-frontend/src/index.css", "r") as f:
    content = f.read()

resolved = """  --success:       #16A05C;
  --success-bg:    #E7F7EF;
  --warning:       #B08020;
  --warning-bg:    #FBF4E0;
  --danger:        #C0392B;
  --danger-bg:     #FDECEA;
  --info:          #4f46e5;
  --font-family:   system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --shadow-sm:     0 1px 2px 0 rgba(28, 35, 51, 0.05);
  --shadow-md:     0 4px 6px -1px rgba(28, 35, 51, 0.05), 0 2px 4px -1px rgba(28, 35, 51, 0.03);
  --shadow-lg:     0 10px 15px -3px rgba(28, 35, 51, 0.06), 0 4px 6px -2px rgba(28, 35, 51, 0.03);
  --radius-md:     8px;
  --radius-lg:     12px;
}

.app-container {
  width: 100%;
  min-height: 100vh;
  transition: padding-right 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.app-container.chat-open {
  padding-right: min(400px, 100vw);
}

@media (max-width: 768px) {
  .app-container.chat-open {
    padding-right: 0; /* panel overlays content; overlay dims background instead */
  }"""

# Replace the conflict block
conflict_pattern = re.compile(r'<<<<<<< HEAD.*?=======\n(.*?)\n>>>>>>> [a-f0-9]+.*?\n', re.DOTALL)
new_content = re.sub(conflict_pattern, resolved + '\n', content)

with open("react-frontend/src/index.css", "w") as f:
    f.write(new_content)
