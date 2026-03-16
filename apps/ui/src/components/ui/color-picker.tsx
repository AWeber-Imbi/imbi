import { useEffect, useRef, useState } from 'react'

const PRESET_COLORS = [
  '#EF4444', '#F59E0B', '#EAB308', '#22C55E',
  '#3B82F6', '#A855F7', '#EC4899', '#6B7280',
]

interface ColorPickerProps {
  value: string
  onChange: (color: string) => void
  isDarkMode: boolean
}

export function ColorPicker({ value, onChange, isDarkMode }: ColorPickerProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [hexInput, setHexInput] = useState(value)

  useEffect(() => {
    setHexInput(value)
  }, [value])

  const handleSwatchClick = () => {
    inputRef.current?.click()
  }

  return (
    <div className="space-y-3">
      <label className={`block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
        Label Color
      </label>

      {/* Preset swatches */}
      <div className="grid grid-cols-4 gap-3 max-w-xs">
        {PRESET_COLORS.map((color) => (
          <button
            key={color}
            type="button"
            onClick={() => onChange(color)}
            className={`w-12 h-12 rounded-lg transition-all ${
              value && value.toUpperCase() === color.toUpperCase()
                ? 'ring-2 ring-offset-2 ring-blue-500'
                : 'hover:scale-105'
            }`}
            style={{ backgroundColor: color }}
            title={color}
          />
        ))}
      </div>

      {/* Selected color + hex input */}
      <div className="flex items-center gap-3 max-w-xs">
        <button
          type="button"
          onClick={handleSwatchClick}
          className={`w-10 h-10 rounded-lg border flex-shrink-0 cursor-pointer ${
            !value ? (isDarkMode ? 'bg-gray-700 border-gray-600' : 'bg-gray-100 border-gray-300') : ''
          }`}
          style={value ? { backgroundColor: value } : undefined}
          title={value ? 'Click to change color' : 'Click to pick a color'}
        />
        <input
          ref={inputRef}
          type="color"
          value={value || '#000000'}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          className="sr-only"
        />
        <input
          type="text"
          value={hexInput}
          onChange={(e) => {
            const v = e.target.value.toUpperCase()
            if (!/^$|^#[0-9A-F]{0,6}$/.test(v)) return
            setHexInput(v)
            if (v === '' || /^#[0-9A-F]{6}$/.test(v)) {
              onChange(v)
            }
          }}
          placeholder="#3B82F6"
          maxLength={7}
          className={`flex-1 px-3 py-2 rounded-lg border text-sm ${
            isDarkMode
              ? 'bg-gray-700 border-gray-600 text-white placeholder:text-gray-400'
              : 'bg-gray-100 border-gray-200 text-gray-900 placeholder:text-gray-500'
          }`}
        />
      </div>

      <p className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
        This color will be used for labels whenever this environment is displayed
      </p>
    </div>
  )
}
