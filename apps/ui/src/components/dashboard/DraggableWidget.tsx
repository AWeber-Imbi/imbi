import { useRef } from 'react'
import { useDrag, useDrop } from 'react-dnd'
import { GripVertical } from 'lucide-react'

interface DraggableWidgetProps {
  id: string
  index: number
  children: React.ReactNode
  onMove: (dragIndex: number, hoverIndex: number) => void
  isDarkMode: boolean
}

const ItemType = 'WIDGET'

export function DraggableWidget({ id, index, children, onMove, isDarkMode }: DraggableWidgetProps) {
  const ref = useRef<HTMLDivElement>(null)

  const [{ isDragging }, drag] = useDrag({
    type: ItemType,
    item: { id, index },
    collect: (monitor) => ({
      isDragging: monitor.isDragging(),
    }),
  })

  const [{ isOver }, drop] = useDrop({
    accept: ItemType,
    hover: (item: { id: string; index: number }, monitor) => {
      if (!ref.current) {
        return
      }
      const dragIndex = item.index
      const hoverIndex = index

      if (dragIndex === hoverIndex) {
        return
      }

      const hoverBoundingRect = ref.current.getBoundingClientRect()
      const hoverMiddleY = (hoverBoundingRect.bottom - hoverBoundingRect.top) / 2
      const clientOffset = monitor.getClientOffset()

      if (!clientOffset) {
        return
      }

      const hoverClientY = clientOffset.y - hoverBoundingRect.top

      if (dragIndex < hoverIndex && hoverClientY < hoverMiddleY) {
        return
      }

      if (dragIndex > hoverIndex && hoverClientY > hoverMiddleY) {
        return
      }

      onMove(dragIndex, hoverIndex)
      item.index = hoverIndex
    },
    collect: (monitor) => ({
      isOver: monitor.isOver(),
    }),
  })

  // Combine drag and drop refs
  drag(drop(ref))

  return (
    <div
      ref={ref}
      className={`relative group cursor-grab active:cursor-grabbing transition-all ${
        isDragging ? 'opacity-40 scale-95' : 'opacity-100 scale-100'
      } ${
        isOver ? (isDarkMode ? 'ring-2 ring-blue-500 shadow-lg' : 'ring-2 ring-[#2A4DD0] shadow-lg') : ''
      }`}
      title="Click and hold to drag"
    >
      {/* Drag indicator - subtle hint */}
      <div
        className={`absolute top-3 left-3 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10 ${
          isDarkMode ? 'text-gray-600' : 'text-gray-300'
        }`}
      >
        <GripVertical className="w-4 h-4" />
      </div>

      {children}
    </div>
  )
}
