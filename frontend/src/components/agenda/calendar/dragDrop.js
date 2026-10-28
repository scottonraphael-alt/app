// Glisser-déposer d'un élément du calendrier vers un autre jour (souris et stylet ; sur tactile, on passe par « Modifier »).
import { isMovable } from "../calendarModel";

let current = null;

export function currentDrag() {
  return current;
}

// Attributs à étaler sur un élément déplaçable ; vide si l'élément ne peut pas être déplacé.
export function dragSource(item, fromDay, enabled = true) {
  if (!enabled || !isMovable(item)) return {};
  return {
    draggable: true,
    onDragStart: (event) => {
      current = { item, fromDay };
      event.stopPropagation();
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        try {
          event.dataTransfer.setData("text/plain", item.title || "");
        } catch (error) {
          // Certains navigateurs refusent setData : le déplacement fonctionne sans.
        }
      }
    },
    onDragEnd: () => {
      current = null;
    },
  };
}

// Attributs d'une zone de dépôt (un jour). `onDropItem(item, fromDay, toDay)`, `onHover(day|null)` facultatif.
export function dropTarget(day, onDropItem, onHover) {
  return {
    onDragOver: (event) => {
      if (!current) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
      onHover?.(day);
    },
    onDragLeave: (event) => {
      if (!current || event.currentTarget.contains(event.relatedTarget)) return;
      onHover?.(null);
    },
    onDrop: (event) => {
      if (!current) return;
      event.preventDefault();
      const { item, fromDay } = current;
      current = null;
      onHover?.(null);
      onDropItem(item, fromDay, day);
    },
  };
}
