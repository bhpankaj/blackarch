---@param target HL.LayoutTarget
---@param box HL.Box
---@param row integer
---@param rows integer
local function place_in_column(target, box, row, rows)
  local row_height = box.h / rows

  target:place({
    x = box.x,
    y = box.y + (row - 1) * row_height,
    w = box.w,
    h = row_height,
  })
end

---@param column_targets HL.LayoutTarget[]
---@param box HL.Box
local function place_column(column_targets, box)
  local rows = #column_targets
  if rows == 0 then
    return
  end

  for row, target in ipairs(column_targets) do
    place_in_column(target, box, row, rows)
  end
end

---@param ctx HL.LayoutContext
local function recalculate_layout(ctx, num_columns)
  local targets = ctx.targets
  local count = #targets
  num_columns = num_columns or 3 -- Default to 3 if not provided

  if count == 0 then return end

  -- Initialize an array of columns
  local cols = {}
  for i = 1, num_columns do
    cols[i] = {}
  end
  
  -- Distribute targets across the columns using modulo arithmetic
  for i, target in ipairs(targets) do
    local col_idx = ((i - 1) % num_columns) + 1
    table.insert(cols[col_idx], target)
  end

  -- Place each column
  for i, col in ipairs(cols) do
    if #col > 0 then
      place_column(col, ctx:column(i, num_columns))
    end
  end
end

-- local function recalculate_tri_column(ctx)
--   local targets = ctx.targets
--   local count = #targets
--
--   if count == 0 then
--     return
--   end
--
--   if count <= 3 then
--     for i, target in ipairs(targets) do
--       target:place(ctx:column(i, count))
--     end
--
--     return
--   end
--
--   ---@type HL.LayoutTarget[]
--   local left = { targets[1] }
--   ---@type HL.LayoutTarget[]
--   local center = { targets[2] }
--   ---@type HL.LayoutTarget[]
--   local right = { targets[3] }
--   local overflow_columns = { left, right, center }
--
--   for i = 4, count do
--     local column = overflow_columns[((i - 4) % #overflow_columns) + 1]
--     table.insert(column, targets[i])
--   end
--
--   place_column(left, ctx:column(1, 3))
--   place_column(center, ctx:column(2, 3))
--   place_column(right, ctx:column(3, 3))
-- end

local function register()
  hl.layout.register("blackarch", {
    recalculate = recalculate_layout,
  })
end

---@class HL.Custom.LayoutNamespace
---@field register fun(): nil
---@type HL.Custom.LayoutNamespace
local M = {
  register = register,
}

return M
