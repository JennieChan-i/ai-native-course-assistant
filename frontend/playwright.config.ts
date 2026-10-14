import {defineConfig} from '@playwright/test'
export default defineConfig({testDir:'./tests',timeout:120000,workers:1,use:{baseURL:process.env.TEST_BASE_URL || 'http://127.0.0.1:8000',channel:'msedge',headless:true,viewport:{width:1440,height:1000},screenshot:'only-on-failure'},reporter:'list'})
