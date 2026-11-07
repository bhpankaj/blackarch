return {
	"RedsXDD/neopywal.nvim",
	name = "neopywal",
	lazy = false,
	priority = 1000,
	config = function()
		require("neopywal").setup({
			transparent_background = true,
			refresh_colors = true,
		})

		-- The "Silent" loader:
		-- This wraps the colorscheme command to ensure it doesn't
		-- trigger message buffer prompts.
		local function apply_theme()
			vim.cmd("silent! colorscheme neopywal")
			vim.cmd("redraw!")
			-- Ensure no lingering "recompiling" messages stay in the buffer
			vim.cmd("echo ''")
		end

		-- Initial load
		apply_theme()

		-- Ensure it stays in sync without prompts
		vim.api.nvim_create_autocmd("BufWritePost", {
			pattern = "*/.cache/wal/colors.json",
			callback = function()
				apply_theme()
			end,
		})
	end,
}
-- return {
-- 	"RedsXDD/neopywal.nvim",
-- 	name = "neopywal",
-- 	lazy = true, -- Load immediately to apply theme on startup
-- 	priority = 1000, -- Load before other plugins
-- 	config = function()
-- 		require("neopywal").setup({
-- 			-- Set to true if you want transparency
-- 			transparent_background = true,
-- 			-- Automatically refresh colors when pywal updates
-- 			refresh_colors = true,
-- 		})
--
-- 		-- Set the colorscheme
-- 		vim.cmd("colorscheme neopywal")
-- 	end,
-- }
