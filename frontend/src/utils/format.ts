/**
 * 价格和数字格式化工具函数
 *
 * 统一标准：
 * - 价格：根据大小智能调整精度（2-8位），移除末尾零
 * - 金额(USDT)：2位小数，移除末尾零
 * - 数量：根据大小智能调整精度（4-8位），移除末尾零
 * - 百分比：1-2位小数
 * - 手续费：4-6位小数，移除末尾零
 */

/**
 * 移除数字字符串末尾的无效零
 * 用于InputNumber的formatter
 * @example
 * removeTrailingZeros("0.22491700") => "0.224917"
 * removeTrailingZeros("100.00000000") => "100"
 * removeTrailingZeros("0.10000000") => "0.1"
 */
export const removeTrailingZeros = (value: string | number | undefined): string => {
  if (value === undefined || value === null || value === '') return ''
  const str = typeof value === 'number' ? value.toString() : value
  // 移除末尾的零，但保留小数点前的零
  return str.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
}

// ==================== 价格格式化 ====================

/**
 * 智能格式化价格：根据价格大小自动调整精度,包含千位分隔符,自动移除末尾无效的零
 * @param price - 价格数值
 * @returns 格式化后的价格字符串
 *
 * @example
 * formatPrice(98765.43) => "98,765.43" (最多2位小数 + 千位分隔)
 * formatPrice(3946.5) => "3,946.5" (最多4位小数,自动移除末尾零)
 * formatPrice(0.195432) => "0.195432" (最多6位小数)
 * formatPrice(0.22491700) => "0.224917" (自动移除末尾零)
 * formatPrice(0.00001234) => "0.00001234" (最多8位小数)
 */
export const formatPrice = (price: number): string => {
  if (price >= 1000) {
    return price.toLocaleString(undefined, { maximumFractionDigits: 2 })
  } else if (price >= 1) {
    return price.toLocaleString(undefined, { maximumFractionDigits: 4 })
  } else if (price >= 0.01) {
    return price.toLocaleString(undefined, { maximumFractionDigits: 6 })
  } else {
    return price.toLocaleString(undefined, { maximumFractionDigits: 8 })
  }
}

/**
 * 格式化价格显示：固定精度，移除末尾零
 * 用于表格、卡片等显示场景
 * @param price - 价格数值
 * @returns 格式化后的价格字符串（移除末尾零）
 *
 * @example
 * formatPriceDisplay(0.20795) => "0.20795"
 * formatPriceDisplay(100.0000) => "100"
 * formatPriceDisplay(0.1) => "0.1"
 */
export const formatPriceDisplay = (price: number | string | undefined): string => {
  if (price === undefined || price === null || price === '') return '--'
  const num = typeof price === 'string' ? parseFloat(price) : price
  if (isNaN(num)) return '--'

  let formatted: string
  if (num >= 100) {
    formatted = num.toFixed(2)
  } else if (num >= 1) {
    formatted = num.toFixed(4)
  } else if (num >= 0.01) {
    formatted = num.toFixed(6)
  } else {
    formatted = num.toFixed(8)
  }

  return removeTrailingZeros(formatted)
}

// ==================== 金额格式化 (USDT) ====================

/**
 * 格式化金额（USDT价值、成交额等）
 * 统一使用2位小数，移除末尾零
 */
export const formatAmount = (amount: number | string | undefined): string => {
  if (amount === undefined || amount === null || amount === '') return '--'
  const num = typeof amount === 'string' ? parseFloat(amount) : amount
  if (isNaN(num)) return '--'
  return removeTrailingZeros(num.toFixed(2))
}

/**
 * 格式化金额显示（USDT），带千位分隔符
 * @param amount - 金额数值
 * @returns 格式化后的金额字符串
 *
 * @example
 * formatAmountDisplay(12345.67) => "12,345.67"
 * formatAmountDisplay(100.00) => "100"
 */
export const formatAmountDisplay = (amount: number | string | undefined): string => {
  if (amount === undefined || amount === null || amount === '') return '--'
  const num = typeof amount === 'string' ? parseFloat(amount) : amount
  if (isNaN(num)) return '--'

  const formatted = num.toFixed(2)
  const cleaned = removeTrailingZeros(formatted)

  // 添加千位分隔符
  const parts = cleaned.split('.')
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return parts.join('.')
}

// ==================== 数量格式化 ====================

/**
 * 格式化数量（币种数量）
 * 根据数量大小自动调整精度，自动移除末尾的0
 */
export const formatQuantity = (quantity: number | string | undefined): string => {
  if (quantity === undefined || quantity === null || quantity === '') return '--'
  const num = typeof quantity === 'string' ? parseFloat(quantity) : quantity
  if (isNaN(num)) return '--'

  let formatted: string
  if (num >= 1) {
    formatted = num.toFixed(4) // ≥1 -> 4位小数
  } else if (num >= 0.0001) {
    formatted = num.toFixed(6) // ≥0.0001 -> 6位小数
  } else {
    formatted = num.toFixed(8) // <0.0001 -> 8位小数
  }
  // 移除末尾的0
  return removeTrailingZeros(formatted)
}

/**
 * 格式化数量显示：固定8位小数，移除末尾零
 * 用于订单数量、持仓数量等场景
 * @param quantity - 数量数值
 * @returns 格式化后的数量字符串
 *
 * @example
 * formatQuantityDisplay(801.29746) => "801.2975"
 * formatQuantityDisplay(0.00123000) => "0.00123"
 */
export const formatQuantityDisplay = (quantity: number | string | undefined): string => {
  if (quantity === undefined || quantity === null || quantity === '') return '--'
  const num = typeof quantity === 'string' ? parseFloat(quantity) : quantity
  if (isNaN(num)) return '--'

  const formatted = num.toFixed(8)
  return removeTrailingZeros(formatted)
}

// ==================== 百分比格式化 ====================

/**
 * 格式化百分比
 * @param percent - 百分比数值（已经是百分比形式，如 50 表示 50%）
 * @param decimals - 小数位数，默认2位
 * @returns 格式化后的百分比字符串（不含%符号）
 *
 * @example
 * formatPercent(50.123, 2) => "50.12"
 * formatPercent(0.5, 1) => "0.5"
 */
export const formatPercent = (
  percent: number | string | undefined,
  decimals: number = 2,
): string => {
  if (percent === undefined || percent === null || percent === '') return '--'
  const num = typeof percent === 'string' ? parseFloat(percent) : percent
  if (isNaN(num)) return '--'
  return removeTrailingZeros(num.toFixed(decimals))
}

/**
 * 格式化百分比显示（带%符号）
 * @param percent - 百分比数值（0-100）
 * @param decimals - 小数位数，默认2位
 * @returns 格式化后的百分比字符串（含%符号）
 *
 * @example
 * formatPercentDisplay(50.123) => "50.12%"
 * formatPercentDisplay(0.5, 1) => "0.5%"
 */
export const formatPercentDisplay = (
  percent: number | string | undefined,
  decimals: number = 2,
): string => {
  const formatted = formatPercent(percent, decimals)
  return formatted === '--' ? '--' : `${formatted}%`
}

// ==================== 手续费格式化 ====================

/**
 * 格式化手续费显示
 * @param fee - 手续费数值
 * @param decimals - 小数位数，默认4位
 * @returns 格式化后的手续费字符串
 *
 * @example
 * formatFeeDisplay(0.641037968) => "0.641"
 * formatFeeDisplay(0.0001234) => "0.000123"
 */
export const formatFeeDisplay = (
  fee: number | string | undefined,
  decimals: number = 4,
): string => {
  if (fee === undefined || fee === null || fee === '') return '--'
  const num = typeof fee === 'string' ? parseFloat(fee) : fee
  if (isNaN(num)) return '--'

  // 根据手续费大小自动调整精度
  if (num >= 1) {
    return removeTrailingZeros(num.toFixed(decimals))
  } else if (num >= 0.0001) {
    return removeTrailingZeros(num.toFixed(Math.max(decimals, 6)))
  } else {
    return removeTrailingZeros(num.toFixed(8))
  }
}

// ==================== 统一导出 ====================

/**
 * 格式化工具集合
 * 可以按需导入单个函数，也可以导入整个工具对象
 */
export const formatUtils = {
  // 基础工具
  removeTrailingZeros,

  // 价格
  formatPrice,
  formatPriceDisplay,

  // 金额 (USDT)
  formatAmount,
  formatAmountDisplay,

  // 数量
  formatQuantity,
  formatQuantityDisplay,

  // 百分比
  formatPercent,
  formatPercentDisplay,

  // 手续费
  formatFeeDisplay,
}

export default formatUtils
