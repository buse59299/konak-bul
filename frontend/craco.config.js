// craco.config.js
const path = require("path");
require("dotenv").config();

module.exports = {
  webpack: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
    configure: (webpackConfig) => {
      // Sorun çıkaran ESLint plugin'ini devre dışı bırakıyoruz
      webpackConfig.plugins = webpackConfig.plugins.filter(
        (plugin) => plugin.constructor.name !== "ESLintWebpackPlugin"
      );
      
      // Hot Module Replacement (HMR) ile ilgili ayarlar
      // Bu ayarlar bazen Windows üzerinde dosya değişikliklerini algılamada sorun yaşatabilir
      // Eğer 'watch' sorunu yaşarsanız burayı özelleştirebilirsiniz.
      
      return webpackConfig;
    },
  },
};