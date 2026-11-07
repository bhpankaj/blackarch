-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here
vim.keymap.set("n", "<A-n>", ":tabnew<CR>", { noremap = true })
-- Navigate between tabs (tabpages) using Alt + Left/Right
vim.keymap.set("n", "<A-Left>", "gT", { noremap = true, silent = true })
vim.keymap.set("n", "<A-Right>", "gt", { noremap = true, silent = true })

-- Optional: Move current tab to the left or right using Alt + Up/Down
vim.keymap.set("n", "<A-Up>", ":tabmove -1<CR>", { noremap = true, silent = true })
vim.keymap.set("n", "<A-Down>", ":tabmove +1<CR>", { noremap = true, silent = true })
