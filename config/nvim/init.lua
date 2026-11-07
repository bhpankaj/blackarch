vim.opt.termguicolors = true
require("blackarch.core")
require("blackarch.lazy")
require("blackarch.lsp")
require("conform").setup({
  formatters_by_ft = {
    lua = { "stylua" },
  },
  format_on_save = function(bufnr)
    -- Disable for Lua files
    if vim.bo[bufnr].filetype == "lua" then
      return nil
    end
    
    return {
      lsp_fallback = true,
      async = false,
      timeout_ms = 3000,
    }
  end,
})
