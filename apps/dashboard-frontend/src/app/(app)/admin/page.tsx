"use client";

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useState } from 'react'

export default function AdminPanelPage() {
  const [activeSection, setActiveSection] = useState('overview')
  
  const adminSections = [
    { id: 'overview', name: 'Overview', icon: '📊' },
    { id: 'users', name: 'User Management', icon: '👥' },
    { id: 'permissions', name: 'Permissions', icon: '🔐' },
    { id: 'system', name: 'System Settings', icon: '⚙️' },
    { id: 'monitoring', name: 'System Monitoring', icon: '📈' },
    { id: 'maintenance', name: 'Maintenance', icon: '🔧' }
  ]
  
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-2">
        <h1 className="text-2xl font-bold text-gray-900">Admin Panel</h1>
        <p className="text-gray-600">
          System administration, user management, and configuration
        </p>
      </div>

      {/* Admin Navigation */}
      <div className="border-b border-gray-200">
        <nav className="flex space-x-8">
          {adminSections.map((section) => (
            <button
              key={section.id}
              onClick={() => setActiveSection(section.id)}
              className={`py-2 px-1 border-b-2 font-medium text-sm transition-colors flex items-center space-x-2 ${
                activeSection === section.id
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-600 hover:text-gray-900'
              }`}
            >
              <span>{section.icon}</span>
              <span>{section.name}</span>
            </button>
          ))}
        </nav>
      </div>

      {/* Content based on active section */}
      {activeSection === 'overview' && (
        <div className="space-y-6">
          {/* System Status Cards */}
          <div className="grid gap-4 md:grid-cols-4">
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center space-x-2 mb-2">
                  <span className="text-lg">🟢</span>
                  <h3 className="text-sm font-medium text-gray-600">System Status</h3>
                </div>
                <div className="text-2xl font-bold text-green-600">Online</div>
                <p className="text-sm text-gray-500">All services operational</p>
              </CardContent>
            </Card>
            
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center space-x-2 mb-2">
                  <span className="text-lg">👥</span>
                  <h3 className="text-sm font-medium text-gray-600">Active Users</h3>
                </div>
                <div className="text-2xl font-bold text-gray-900">23</div>
                <p className="text-sm text-gray-500">Currently online</p>
              </CardContent>
            </Card>
            
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center space-x-2 mb-2">
                  <span className="text-lg">💾</span>
                  <h3 className="text-sm font-medium text-gray-600">Storage</h3>
                </div>
                <div className="text-2xl font-bold text-gray-900">78%</div>
                <p className="text-sm text-gray-500">Database usage</p>
              </CardContent>
            </Card>
            
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center space-x-2 mb-2">
                  <span className="text-lg">🔄</span>
                  <h3 className="text-sm font-medium text-gray-600">Last Backup</h3>
                </div>
                <div className="text-2xl font-bold text-gray-900">2h</div>
                <p className="text-sm text-gray-500">ago</p>
              </CardContent>
            </Card>
          </div>
          
          {/* Recent Activity */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-semibold">Recent Admin Activity</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="flex items-center justify-between p-3 bg-gray-50 rounded">
                  <div>
                    <div className="font-medium text-sm">System backup completed</div>
                    <div className="text-xs text-gray-600">Automated daily backup</div>
                  </div>
                  <div className="text-xs text-gray-500">2 hours ago</div>
                </div>
                <div className="flex items-center justify-between p-3 bg-gray-50 rounded">
                  <div>
                    <div className="font-medium text-sm">New user registered: analyst@hawanama.org</div>
                    <div className="text-xs text-gray-600">Pending approval</div>
                  </div>
                  <div className="text-xs text-gray-500">4 hours ago</div>
                </div>
                <div className="flex items-center justify-between p-3 bg-gray-50 rounded">
                  <div>
                    <div className="font-medium text-sm">Station permissions updated</div>
                    <div className="text-xs text-gray-600">IQAir stations access granted to research team</div>
                  </div>
                  <div className="text-xs text-gray-500">1 day ago</div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {activeSection === 'users' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold">User Management</h2>
            <button className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors">
              Add New User
            </button>
          </div>
          
          <Card>
            <CardContent>
              <div className="text-center py-8">
                <div className="text-3xl mb-2">👥</div>
                <h4 className="font-medium text-gray-700">User Management System</h4>
                <p className="text-sm text-gray-500 mt-2">
                  Comprehensive user management with role-based access control
                </p>
                <div className="mt-4 text-xs text-gray-400">
                  Implementation: Coming soon
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {activeSection === 'permissions' && (
        <div className="space-y-6">
          <h2 className="text-xl font-semibold">Role & Permission Management</h2>
          
          <Card>
            <CardContent>
              <div className="text-center py-8">
                <div className="text-3xl mb-2">🔐</div>
                <h4 className="font-medium text-gray-700">Permissions System</h4>
                <p className="text-sm text-gray-500 mt-2">
                  Fine-grained access control for stations, data, and features
                </p>
                <div className="mt-4 text-xs text-gray-400">
                  Implementation: Coming soon
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {activeSection === 'system' && (
        <div className="space-y-6">
          <h2 className="text-xl font-semibold">System Configuration</h2>
          
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>API Settings</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div>
                    <label className="text-sm font-medium text-gray-700">Rate Limits</label>
                    <div className="mt-1 text-sm text-gray-600">Configure API rate limiting</div>
                  </div>
                  <div>
                    <label className="text-sm font-medium text-gray-700">Cache Settings</label>
                    <div className="mt-1 text-sm text-gray-600">Data caching configuration</div>
                  </div>
                  <button className="w-full py-2 px-4 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors">
                    Configure API
                  </button>
                </div>
              </CardContent>
            </Card>
            
            <Card>
              <CardHeader>
                <CardTitle>Data Retention</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div>
                    <label className="text-sm font-medium text-gray-700">Historical Data</label>
                    <div className="mt-1 text-sm text-gray-600">Configure data retention policies</div>
                  </div>
                  <div>
                    <label className="text-sm font-medium text-gray-700">Backup Schedule</label>
                    <div className="mt-1 text-sm text-gray-600">Automated backup configuration</div>
                  </div>
                  <button className="w-full py-2 px-4 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors">
                    Configure Storage
                  </button>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {activeSection === 'monitoring' && (
        <div className="space-y-6">
          <h2 className="text-xl font-semibold">System Monitoring</h2>
          
          <Card>
            <CardContent>
              <div className="text-center py-8">
                <div className="text-3xl mb-2">📈</div>
                <h4 className="font-medium text-gray-700">System Health Dashboard</h4>
                <p className="text-sm text-gray-500 mt-2">
                  Real-time monitoring of system performance, API health, and resource usage
                </p>
                <div className="mt-4 text-xs text-gray-400">
                  Monitoring integration: Coming soon
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {activeSection === 'maintenance' && (
        <div className="space-y-6">
          <h2 className="text-xl font-semibold">System Maintenance</h2>
          
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Database Maintenance</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  <button className="w-full py-2 px-4 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors text-left">
                    🔄 Run Database Cleanup
                  </button>
                  <button className="w-full py-2 px-4 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors text-left">
                    📊 Analyze Query Performance
                  </button>
                  <button className="w-full py-2 px-4 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors text-left">
                    💾 Force Database Backup
                  </button>
                </div>
              </CardContent>
            </Card>
            
            <Card>
              <CardHeader>
                <CardTitle>Cache Management</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  <button className="w-full py-2 px-4 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors text-left">
                    🗑️ Clear All Caches
                  </button>
                  <button className="w-full py-2 px-4 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors text-left">
                    🔄 Refresh Station Cache
                  </button>
                  <button className="w-full py-2 px-4 text-sm font-medium text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors text-left">
                    📈 Cache Performance Stats
                  </button>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}