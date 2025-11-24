import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"

interface TabsProps {
  children: React.ReactNode
  className?: string
}

interface TabsListProps {
  children: React.ReactNode
  className?: string
}

interface TabsLinkProps {
  href: string
  children: React.ReactNode
  className?: string
}

const Tabs = React.forwardRef<HTMLDivElement, TabsProps>(
  ({ className, children, ...props }, ref) => (
    <div ref={ref} className={cn("w-full", className)} {...props}>
      {children}
    </div>
  )
)
Tabs.displayName = "Tabs"

const TabsList = React.forwardRef<HTMLDivElement, TabsListProps>(
  ({ className, children, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "inline-flex h-10 items-center justify-center rounded-md bg-muted p-1 text-muted-foreground",
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
)
TabsList.displayName = "TabsList"

const TabsLink = React.forwardRef<HTMLAnchorElement, TabsLinkProps>(
  ({ className, href, children, ...props }, ref) => {
    const pathname = usePathname()
    const isActive = pathname === href || 
      (href.includes('/stations/') && pathname.startsWith(href))

    return (
      <Link
        ref={ref}
        href={href}
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
          isActive
            ? "bg-background text-foreground shadow-sm"
            : "hover:bg-background/50",
          className
        )}
        {...props}
      >
        {children}
      </Link>
    )
  }
)
TabsLink.displayName = "TabsLink"

export { Tabs, TabsList, TabsLink }