return {
	"EdenEast/nightfox.nvim",
	priority = 1000, -- Ensure it loads first
	config = function()
		require("nightfox").setup({
			options = {
				-- Compiled file's destination location
				compile_path = vim.fn.stdpath("cache") .. "/nightfox",
				compile_file_suffix = "_compiled", -- Compiled file suffix
				transparent = true, -- Disable setting background
			},
			palettes = {
				all = {
					bg0 = "None",
					black = { dim = "#0F1012", base = "#1B1D21", bright = "#2C2E33" },
					red = { dim = "#CC4444", base = "#FF5555", bright = "#FF6E6E" },
					green = { dim = "#3CC968", base = "#50FA7B", bright = "#69FF94" },
					yellow = { dim = "#D4DB77", base = "#F1FA8C", bright = "#FFFFA5" },
					blue = { dim = "#1A7ACC", base = "#1E90FF", bright = "#63B3FF" },
					magenta = { dim = "#6A5ACD", base = "#9370DB", bright = "#BA55D3" },
					cyan = { dim = "#70C9E3", base = "#8BE9FD", bright = "#A4FFFF" },
					white = { dim = "#AAAAAA", base = "#BBBBBB", bright = "#FFFFFF" },
					orange = { dim = "#CC8244", base = "#FFB86C", bright = "#FFD191" },
					pink = { dim = "#CC62A6", base = "#FF79C6", bright = "#FF92DF" },
				},
			},
		})
	end,
	{
		"LazyVim/LazyVim",
		opts = {
			colorscheme = "carbonfox",
		},
	},
}
