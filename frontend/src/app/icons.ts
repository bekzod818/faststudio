import {
  Box,
  Building2,
  CalendarDays,
  CreditCard,
  Database,
  File,
  FileText,
  Folder,
  Globe,
  Image,
  Key,
  Mail,
  MapPin,
  MessageSquare,
  Package,
  Settings,
  ShoppingCart,
  Tag,
  User,
  Users,
  type LucideIcon,
} from "lucide-react";

/**
 * Icons available to `ModelAdmin.icon`. A curated set keeps the bundled SPA
 * small (importing every lucide icon would ship thousands of modules).
 */
const ICONS: Record<string, LucideIcon> = {
  box: Box,
  "building-2": Building2,
  "calendar-days": CalendarDays,
  "credit-card": CreditCard,
  database: Database,
  file: File,
  "file-text": FileText,
  folder: Folder,
  globe: Globe,
  image: Image,
  key: Key,
  mail: Mail,
  "map-pin": MapPin,
  "message-square": MessageSquare,
  package: Package,
  settings: Settings,
  "shopping-cart": ShoppingCart,
  tag: Tag,
  user: User,
  users: Users,
};

export function modelIcon(name: string | null | undefined): LucideIcon {
  // Own keys only: names like "constructor" must not resolve to Object.prototype.
  return name && Object.hasOwn(ICONS, name) ? (ICONS[name] ?? Database) : Database;
}
