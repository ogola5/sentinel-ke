FROM node:20

WORKDIR /usr/src/app

# install deps
COPY package.json package-lock.json* ./
RUN npm install

# copy everything else
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host"]
