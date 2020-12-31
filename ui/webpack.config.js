const path = require('path');
const CopyWebpackPlugin = require('copy-webpack-plugin')

module.exports = {
  entry: ['babel-polyfill', __dirname + '/src/js/index.jsx'],
  output: {
    path: path.resolve(__dirname, '../imbi/static/js/'),
    filename: 'imbi.js',
  },
  performance: {hints: false},
  resolve: {
    extensions: ['.js', '.jsx']
  },
  module: {
    rules: [
      {
        test: /\.js?/,
        exclude: /node_modules/,
        use: 'babel-loader'
      },
      {
        test: /\.css$/i,
        use: ["style-loader", "css-loader", "postcss-loader"]
      }
    ]
  },
  plugins: [
    new CopyWebpackPlugin(
      {
        patterns: [
          {
            from: 'node_modules/@fortawesome/fontawesome-free/webfonts/*',
            to: path.resolve(__dirname, '../imbi/static/fonts/'),
            flatten: true
          },
          {
            from: 'node_modules/typeface-inter/Inter Web/*.woff*',
            to: path.resolve(__dirname, '../imbi/static/fonts/'),
            flatten: true
          },
          {
            from: 'node_modules/redoc/bundles/redoc.standalone.js',
            to: path.resolve(__dirname, '../imbi/static/js/'),
            flatten: true
          }
        ]
      }, {})
  ],
  externals: {
    config: JSON.stringify({
      apiUrl: 'http://localhost:8000'
    })
  }
};
