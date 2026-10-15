/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // 专业金融配色 - 深色主题
        primary: {
          DEFAULT: '#1890ff',
          hover: '#40a9ff',
          active: '#096dd9',
        },
        dark: {
          50: '#fafafa',
          100: '#f5f5f5',
          200: '#e5e5e5',
          300: '#d4d4d4',
          400: '#a3a3a3',
          500: '#737373',
          600: '#525252',
          700: '#404040',
          800: '#262626',
          850: '#1a1a1a',
          900: '#171717',
          950: '#0a0a0a',
          bg: '#0d0d0d', // 主背景
          card: '#1a1a1a', // 卡片背景
          border: '#2a2a2a', // 边框
          hover: '#222222', // 悬停
        },
        // 金融专用色
        up: '#22c55e', // 涨 - 专业绿
        down: '#ef4444', // 跌 - 专业红
        warning: '#f59e0b', // 警告
        info: '#3b82f6', // 信息
      },
      fontFamily: {
        mono: ['SF Mono', 'Monaco', 'Cascadia Code', 'Roboto Mono', 'monospace'],
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      boxShadow: {
        card: '0 1px 3px 0 rgba(0, 0, 0, 0.3)',
        'card-hover': '0 4px 6px -1px rgba(0, 0, 0, 0.4)',
      },
    },
  },
  plugins: [],
  // 与Ant Design兼容
  corePlugins: {
    preflight: false,
  },
}
