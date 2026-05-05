import React from 'react';
import { Calendar, ChevronDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export type DateRange = 'today' | '7d' | '30d' | 'all';

interface Props {
    value: DateRange;
    onChange: (range: DateRange) => void;
    dark?: boolean;
}

export const DateRangePicker: React.FC<Props> = ({ value, onChange, dark }) => {
    const { t } = useTranslation();

    const options: { id: DateRange; label: string }[] = [
        { id: 'today', label: t('Today', 'Hoy') },
        { id: '7d', label: t('Last 7 days', 'Últimos 7 días') },
        { id: '30d', label: t('This month', 'Este mes') },
        { id: 'all', label: t('All time', 'Todo') },
    ];

    return (
        <div className="flex bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-1 rounded-xl shadow-sm">
            {options.map((opt) => (
                <button
                    key={opt.id}
                    onClick={() => onChange(opt.id)}
                    className={`px-4 py-1.5 text-xs font-bold rounded-lg transition-all ${value === opt.id
                            ? 'bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 shadow-sm'
                            : 'text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700'
                        }`}
                >
                    {opt.label}
                </button>
            ))}
        </div>
    );
};

export const getDatesFromRange = (range: DateRange) => {
    const now = new Date();
    const start = new Date();

    if (range === 'today') {
        start.setHours(0, 0, 0, 0);
    } else if (range === '7d') {
        start.setDate(now.getDate() - 7);
    } else if (range === '30d') {
        start.setDate(now.getDate() - 30);
    } else {
        return { start: undefined, end: undefined };
    }

    return {
        start: start.toISOString(),
        end: now.toISOString()
    };
};
