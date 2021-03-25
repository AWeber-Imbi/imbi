const path = require('path')
const process = require('process')

const dev = process.env.NODE_ENV !== 'production'

let publicPath = '/static/'
if (dev) publicPath = 'http://0.0.0.0:8080/static/'

module.exports = {
  entry: ['babel-polyfill', __dirname + '/src/js/index.jsx'],
  output: {
    path: path.resolve(__dirname, '../imbi/static/'),
    publicPath: publicPath,
    filename: 'imbi.js'
  },
  devServer: {
    hot: true,
    inline: true,
    lazy: false,
    headers: {"Access-Control-Allow-Origin": "*"},
  },
  devtool: dev ? 'eval-cheap-module-source-map' : 'source-map',
  performance: { hints: false },
  resolve: {
    extensions: ['.js', '.jsx']
  },
  module: {
    rules: [
      {
        test: /\.(js|jsx)$/,
        exclude: /node_modules/,
        loader: 'babel-loader'
      },
      {
        test: /\.(svg)$/,
        loader: 'file-loader',
        options: {
          name: '[name].[ext]',
          outputPath: 'images/'
        }
      },
      {
        test: /\.(woff(2)?|ttf|eot)(\?v=\d+\.\d+\.\d+)?$/,
        loader: 'file-loader',
        options: {
          name: '[name].[ext]',
          outputPath: 'fonts/'
        }
      },
      {
        test: /\.css$/i,
        use: [
          'style-loader',
          'css-loader',
          'resolve-url-loader',
          'postcss-loader'
        ]
      }
    ]
  },
  plugins: [],
  watchOptions: {
    aggregateTimeout: 1000,
    ignored: 'node_modules/**',
    poll: 1000
  }
}
