
import React from 'react';
import { NavLink } from 'react-router-dom';

interface SidebarItemProps {
  icon: React.ReactNode;
  label: string;
  to: string;
  collapsed?: boolean;
  /** Pass end=true on the root "/" route so it only matches exactly */
  end?: boolean;
}

const SidebarItem: React.FC<SidebarItemProps> = ({ icon, label, to, collapsed, end }) => {
  return (
    <NavLink
      to={to}
      end={end}
      title={collapsed ? label : undefined}
      className={({ isActive }) => `
        flex items-center gap-3 w-full px-3 py-2 text-sm rounded-lg transition-all duration-200
        ${isActive
          ? 'bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-gray-100 font-medium'
          : 'text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50 hover:text-gray-900 dark:hover:text-gray-100'
        }
        ${collapsed ? 'justify-center' : 'justify-start'}
      `}
    >
      {({ isActive }) => (
        <>
          <span className={isActive ? 'text-gray-900 dark:text-gray-100' : 'text-gray-400 dark:text-gray-500'}>
            {icon}
          </span>
          {!collapsed && <span>{label}</span>}
        </>
      )}
    </NavLink>
  );
};

export default SidebarItem;
